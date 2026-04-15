"""Shared stream sink primitives for provider streaming."""

from __future__ import annotations

import json
import logging
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TextIO

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.schema_registry import read_schema

# Per-path locks for coordinated writes to the same file
_event_write_locks: dict[Path, threading.Lock] = {}
_event_write_locks_lock = threading.Lock()  # Lock for accessing the locks dict


def _get_event_write_lock(path: Path) -> threading.Lock:
    """Get or create a lock for a specific path."""
    with _event_write_locks_lock:
        if path not in _event_write_locks:
            _event_write_locks[path] = threading.Lock()
        return _event_write_locks[path]


class StreamSink(Protocol):
    def write(self, line: str) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


_logger = logging.getLogger(__name__)


@dataclass
class InMemorySink:
    """Collect stream output in memory for the command result.

    Supports bounded capture with configurable overflow policy.
    """

    lines: list[str] = field(default_factory=list)
    max_bytes: int | None = None
    overflow_policy: str = "warn-only"
    overflow_marker: str = "\n[OUTPUT TRUNCATED]\n"
    warning_threshold_bytes: int | None = None
    _current_bytes: int = field(default=0, repr=False)
    _warning_emitted: bool = field(default=False, repr=False)
    _truncated: bool = field(default=False, repr=False)

    def write(self, line: str) -> None:
        line_bytes = len(line.encode("utf-8", errors="replace"))
        marker_bytes = len(self.overflow_marker.encode("utf-8", errors="replace"))

        if self.max_bytes is not None:
            if self._current_bytes + line_bytes > self.max_bytes:
                if self.overflow_policy == "fail":
                    raise MemoryError(
                        f"in-memory sink exceeded max_bytes: {self.max_bytes}"
                    )
                elif self.overflow_policy == "truncate-head":
                    # Account for marker bytes when truncating
                    available = self.max_bytes - marker_bytes - line_bytes
                    while self.lines and self._current_bytes > available:
                        removed = self.lines.pop(0)
                        self._current_bytes -= len(
                            removed.encode("utf-8", errors="replace")
                        )
                    self.lines.append(self.overflow_marker)
                    self._current_bytes += marker_bytes
                    self._truncated = True
                elif self.overflow_policy == "truncate-tail":
                    if not self._truncated:
                        self.lines.append(self.overflow_marker)
                        self._current_bytes += marker_bytes
                        self._truncated = True
                    return
                elif self.overflow_policy == "warn-only":
                    pass

            if (
                self.warning_threshold_bytes
                and self._current_bytes < self.warning_threshold_bytes
                and self._current_bytes + line_bytes >= self.warning_threshold_bytes
                and not self._warning_emitted
            ):
                _logger.warning(
                    "in-memory sink approaching threshold: %d bytes",
                    self.warning_threshold_bytes,
                )
                self._warning_emitted = True

        self.lines.append(line)
        self._current_bytes += line_bytes

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    @property
    def text(self) -> str:
        return "".join(self.lines)


@dataclass
class ConsoleSink:
    """Mirror stream output to a console-like text stream safely."""

    console: TextIO = sys.stdout

    def write(self, line: str) -> None:
        try:
            self.console.write(line)
        except UnicodeEncodeError:
            encoding = getattr(self.console, "encoding", None) or "utf-8"
            safe_text = line.encode(encoding, errors="replace").decode(
                encoding, errors="replace"
            )
            self.console.write(safe_text)
        self.console.flush()

    def flush(self) -> None:
        self.console.flush()

    def close(self) -> None:
        self.console.flush()


@dataclass
class RawLogSink:
    """Append raw stream lines to a durable runtime log."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, line: str) -> None:
        if not line:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            if not line.endswith("\n"):
                handle.write("\n")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


@dataclass
class NormalizedEventSink:
    """Write canonical provider stream events to an ndjson file.

    Supports schema validation, invalid event quarantine, and coordinated writes.
    """

    path: Path
    job_id: str
    prompt_id: str | None = None
    provider_id: str | None = None
    surface: str | None = None
    stage: str | None = None
    stream: str = "stdout"
    event_schema_validation: bool = True
    invalid_event_policy: str = "quarantine"
    event_write_policy: str = "locked-append"
    quarantine_path: Path | None = None

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.event_schema_validation:
            self._validator = Draft202012Validator(read_schema("provider-stream-event"))
        else:
            self._validator = None
        if self.quarantine_path is None:
            self.quarantine_path = (
                self.path.parent / f"{self.path.stem}.invalid{self.path.suffix}"
            )

    def write(self, line: str) -> None:
        text = line.rstrip("\r\n")
        if not text:
            return
        self.write_event(
            {
                "contract-version": "v1",
                "job-id": self.job_id,
                "prompt-id": self.prompt_id,
                "provider-id": self.provider_id,
                "surface": self.surface,
                "stage": self.stage,
                "event-kind": "task-progress",
                "message": text,
                "timestamp": _utc_now(),
                "details": {"stream": self.stream},
            }
        )

    def write_event(self, payload: dict[str, Any]) -> None:
        record = {key: value for key, value in payload.items() if value is not None}

        if self.event_schema_validation and self._validator:
            errors = list(self._validator.iter_errors(record))
            if errors:
                error_msgs = ", ".join(e.message for e in errors)
                if self.invalid_event_policy == "fail":
                    raise ValueError(
                        f"normalized event failed schema validation: {error_msgs}"
                    )
                elif self.invalid_event_policy == "quarantine":
                    _logger.warning("quarantining invalid event: %s", error_msgs)
                    self._quarantine_event(record, error_msgs)
                    return
                elif self.invalid_event_policy == "warn":
                    _logger.warning("skipping invalid event: %s", error_msgs)
                    return

        if self.event_write_policy == "locked-append":
            with _get_event_write_lock(self.path):
                self._append_event(record)
        else:
            self._append_event(record)

    def _append_event(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")

    def _quarantine_event(self, record: dict[str, Any], reason: str) -> None:
        quarantine_record = {
            **record,
            "quarantined-at": _utc_now(),
            "quarantine-reason": reason,
        }
        with self.quarantine_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(quarantine_record, sort_keys=True))
            handle.write("\n")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
