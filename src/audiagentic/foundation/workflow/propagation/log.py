"""Propagation attempt audit log.

The on-disk layout is a JSON list to preserve compatibility with the existing
consumer in ``planning.tm`` and integration tests. Writes are append-only via
read-modify-write — fine for low-volume audit traffic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PropagationLog:
    def __init__(self, path: Path | None):
        self._path = path

    def append(
        self,
        *,
        status: str,
        target_id: str,
        target_state: str,
        source_id: str,
        source_kind: str | None,
        source_state: str,
        metadata: dict[str, Any],
        target_kind: str | None = None,
        old_state: str | None = None,
        reason: str | None = None,
    ) -> None:
        if self._path is None:
            return

        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": metadata.get("correlation_id") or metadata.get("event_id"),
            "correlation_id": metadata.get("correlation_id"),
            "source_kind": source_kind,
            "source_id": source_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "old_state": old_state,
            "new_state": target_state,
            "trigger_source_state": source_state,
            "triggered_by": metadata.get("triggered_by", "automatic"),
            "propagation_depth": metadata.get("propagation_depth", 0),
            "status": status,
        }
        if reason:
            entry["reason"] = reason

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data: list = []
            if self._path.exists():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    data = raw if isinstance(raw, list) else []
                except (json.JSONDecodeError, ValueError):
                    data = []
            data.append(entry)
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Failed to write propagation log entry for %s: %s", target_id, exc)
