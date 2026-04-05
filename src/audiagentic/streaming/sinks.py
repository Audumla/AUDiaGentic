"""Shared stream sink primitives for provider streaming."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TextIO


class StreamSink(Protocol):
    def write(self, line: str) -> None:
        ...

    def flush(self) -> None:
        ...

    def close(self) -> None:
        ...


@dataclass
class InMemorySink:
    """Collect stream output in memory for the command result."""

    lines: list[str] = field(default_factory=list)

    def write(self, line: str) -> None:
        self.lines.append(line)

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
            safe_text = line.encode(encoding, errors="replace").decode(encoding, errors="replace")
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

    def write(self, line: str) -> None:
        if not line:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
    """Write canonical provider stream events to an ndjson file."""

    path: Path
    job_id: str | None = None
    prompt_id: str | None = None
    provider_id: str | None = None
    surface: str | None = None
    stage: str | None = None
    stream: str = "stdout"

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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
