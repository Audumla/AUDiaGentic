"""Generic event logging.

Appends JSONL records to a file. No dependencies on planning or workflow code.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class EventLog:
    """Append-only JSONL event log."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, payload: dict) -> None:
        """Write an event record to the log."""
        rec = {"ts": now_iso(), "event": event, **payload}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
