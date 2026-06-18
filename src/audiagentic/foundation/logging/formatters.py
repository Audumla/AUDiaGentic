"""Logging formatters and handlers for AUDiaGentic."""
from __future__ import annotations

import json
import logging
import logging.handlers
import time
from typing import Any

from audiagentic.foundation.logging.context import get_correlation_id

# All instance attributes set by logging.LogRecord.__init__ — exclude from extras.
_STD_RECORD_ATTRS: frozenset[str] = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs",
    "msg", "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "taskName", "thread", "threadName", "asctime",
})


class _CorrelationJsonFormatter(logging.Formatter):
    """Emit one JSON object per log record matching the defined schema."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        exc_text = None
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)

        doc: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{record.msecs:03.0f}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
            "correlation_id": get_correlation_id(),
            "exc_info": exc_text,
        }

        for key, val in record.__dict__.items():
            if not key.startswith("_") and key not in _STD_RECORD_ATTRS:
                doc[key] = val

        return json.dumps(doc, default=str)


_DEV_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DEV_DATE = "%H:%M:%S"

_ANSI = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
    "RESET": "\033[0m",
}


class _DevFormatter(logging.Formatter):
    def __init__(self, colour: bool = False) -> None:
        super().__init__(_DEV_FORMAT, datefmt=_DEV_DATE)
        self._colour = colour

    def format(self, record: logging.LogRecord) -> str:
        out = super().format(record)
        if self._colour:
            c = _ANSI.get(record.levelname, "")
            r = _ANSI["RESET"]
            out = out.replace(record.levelname, f"{c}{record.levelname}{r}", 1)
        return out


class _ConsoleFormatter(logging.Formatter):
    """Render terminal output as user-facing console lines, not raw log records."""

    def __init__(self, colour: bool = False) -> None:
        super().__init__()
        self._colour = colour

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        prefix = self._prefix(record)
        message = f"{prefix} {record.message}"
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return message

    def _prefix(self, record: logging.LogRecord) -> str:
        if record.name == "audiagentic.launcher":
            label = "AUDiaGentic"
        else:
            label = record.name.rsplit(".", 1)[-1].replace("_", " ")
        if not self._colour:
            return f"[{label}]"
        colour = _ANSI.get(record.levelname, "")
        reset = _ANSI["RESET"]
        return f"{colour}[{label}]{reset}"


class _SafeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Skip rollover when another Windows process still holds log file open."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            if self.stream:
                try:
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

            current_time = int(time.time())
            self.rolloverAt = self.computeRollover(current_time)
            while self.rolloverAt <= current_time:
                self.rolloverAt += self.interval

            if not self.delay:
                self.stream = self._open()
