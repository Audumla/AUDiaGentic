"""Bounded operator trace for gateway-owned provider sessions.

The gateway service normally communicates over HTTP/MCP, so provider launch
activity is otherwise difficult to see while debugging a live CLI process.
This module writes a small, human-readable trace to stderr (never stdout,
which may be an MCP protocol stream).  Summary mode is enabled by default;
set ``AUDIAGENTIC_GATEWAY_CONSOLE_TRACE=off`` to disable it or ``full`` to
include bounded prompt/response bodies.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from audiagentic.foundation.paths.home import global_log_dir

_DEFAULT_MAX_BODY_CHARS = 4096
_PROGRESS_INTERVAL_SECONDS = 5.0
_VALID_MODES = frozenset({"off", "summary", "full"})


def _default_stream() -> TextIO:
    """Open the detached gateway's operator trace sink.

    The managed gateway deliberately has no console and its service host
    discards child stderr/stdout.  Persisting the bounded trace to the shared
    gateway log makes it observable without reintroducing console windows.
    ``AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_FILE`` remains an explicit override;
    stderr is only the safe fallback if the log cannot be opened.
    """

    configured = os.environ.get("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_FILE", "").strip()
    path = Path(os.path.expandvars(configured)) if configured else global_log_dir("gateway") / "console-trace.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("a", encoding="utf-8", buffering=1)
    except OSError:
        return sys.stderr


def _mode() -> str:
    value = os.environ.get("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE", "summary").strip().lower()
    return value if value in _VALID_MODES else "summary"


def _max_body_chars() -> int:
    try:
        value = int(os.environ.get("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_MAX_CHARS", ""))
    except ValueError:
        value = _DEFAULT_MAX_BODY_CHARS
    return max(256, min(value or _DEFAULT_MAX_BODY_CHARS, 1_048_576))


def _safe_body(value: Any) -> str:
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    limit = _max_body_chars()
    return text if len(text) <= limit else text[:limit] + "..."


def _safe_field(value: Any) -> str:
    text = str(value)
    return text.replace("\r", "\\r").replace("\n", "\\n").replace(" ", "_")


@dataclass
class GatewayConsoleTrace:
    """One gateway stderr trace writer.

    The stream is injectable for tests.  A lock prevents interleaved lines
    when several sessions progress concurrently in the gateway service.
    """

    stream: TextIO | None = None
    clock: Any = time.monotonic

    def __post_init__(self) -> None:
        if self.stream is None:
            self.stream = _default_stream()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return _mode() != "off"

    @property
    def full(self) -> bool:
        return _mode() == "full"

    def _write(self, event: str, **fields: Any) -> None:
        if not self.enabled:
            return
        timestamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        rendered = " ".join(
            f"{key}={_safe_body(value) if key in {'prompt', 'output'} else _safe_field(value)}"
            for key, value in fields.items()
            if value is not None
        )
        line = f"[{timestamp}] {event}" + (f" {rendered}" if rendered else "")
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()

    def session_opened(
        self,
        *,
        session_id: str,
        provider_id: str,
        model_id: str | None,
        execution_profile_id: str,
        surface_id: str | None,
        child_pid: int | None,
    ) -> None:
        self._write(
            "START",
            provider=provider_id,
            model=model_id,
            harness=surface_id,
            profile=execution_profile_id,
            session=session_id,
            pid=child_pid,
        )

    def turn_started(
        self,
        *,
        request_id: str,
        session_id: str,
        prompt: str,
    ) -> float:
        started = self.clock()
        fields: dict[str, Any] = {
            "request": request_id,
            "session": session_id,
            "prompt_chars": len(prompt),
        }
        if self.full:
            fields["prompt"] = _safe_body(prompt)
        self._write("TURN", **fields)
        return started

    def progress(
        self,
        *,
        request_id: str,
        session_id: str,
        kind: str,
        sequence: int | None,
        started: float,
        force: bool = False,
    ) -> None:
        now = self.clock()
        last = getattr(self, "_last_progress", {}).get(request_id)
        last_kind = getattr(self, "_last_kind", {}).get(request_id)
        if not force and last is not None and now - last < _PROGRESS_INTERVAL_SECONDS and kind == last_kind:
            return
        if not hasattr(self, "_last_progress"):
            self._last_progress = {}
            self._last_kind = {}
        self._last_progress[request_id] = now
        self._last_kind[request_id] = kind
        self._write(
            "PROGRESS",
            request=request_id,
            session=session_id,
            activity=kind,
            sequence=sequence,
            elapsed=f"{now - started:.1f}s",
        )

    def finished(
        self,
        *,
        request_id: str,
        session_id: str,
        outcome: str | None,
        output: str | None,
        error_code: str | None = None,
        started: float,
    ) -> None:
        fields: dict[str, Any] = {
            "request": request_id,
            "session": session_id,
            "outcome": outcome,
            "output_chars": len(output or ""),
            "error_code": error_code,
            "elapsed": f"{self.clock() - started:.1f}s",
        }
        if self.full and output:
            fields["output"] = _safe_body(output)
        self._write("COMPLETE", **fields)
        getattr(self, "_last_progress", {}).pop(request_id, None)
        getattr(self, "_last_kind", {}).pop(request_id, None)

    def failed(
        self,
        *,
        request_id: str,
        session_id: str,
        error_code: str | None,
        error_type: str,
        started: float,
    ) -> None:
        self._write(
            "FAILED",
            request=request_id,
            session=session_id,
            error_code=error_code,
            error_type=error_type,
            elapsed=f"{self.clock() - started:.1f}s",
        )


__all__ = ["GatewayConsoleTrace"]
