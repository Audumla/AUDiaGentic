"""Shared append-only observability timeline helpers."""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from audiagentic.foundation.logging.context import get_correlation_id
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.observability.journal_segments import journal_lock, prepare_append, compact_indexed_ndjson

logger = logging.getLogger(__name__)

_timeline_locks: dict[Path, threading.Lock] = {}
_timeline_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _timeline_locks_guard:
        lock = _timeline_locks.get(resolved)
        if lock is None:
            lock = threading.Lock()
            _timeline_locks[resolved] = lock
        return lock


def record_timeline_event(
    path: Path,
    *,
    component: str,
    resource_kind: str,
    resource_id: str,
    event: str,
    state: str | None = None,
    attributes: dict[str, Any] | None = None,
    timestamp: str | None = None,
    correlation_id: str | None = None,
    segment_max_bytes: int | None = None,
) -> dict[str, Any]:
    """Append one durable JSONL timeline event.

    Best-effort by design: observability must not break primary mutations.
    """
    attrs = attributes or {}
    resolved_correlation_id = (
        correlation_id
        or attrs.get("correlation_id")
        or attrs.get("correlation-id")
        or get_correlation_id()
    )
    record = {
        "contract-version": "v1",
        "timestamp": timestamp or now_iso_z("microseconds"),
        "component": component,
        "resource-kind": resource_kind,
        "resource-id": resource_id,
        "correlation-id": resolved_correlation_id,
        "event": event,
        "state": state,
        "attributes": attrs,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock_for(path), (journal_lock(path) if segment_max_bytes is not None else nullcontext()):
            line = json.dumps(record, sort_keys=True) + "\n"
            index_path = path.with_suffix(".index.ndjson")
            if segment_max_bytes is not None:
                prepare_append(path, index_path, max_bytes=segment_max_bytes,
                               incoming_bytes=len(line.encode("utf-8")))
            offset = path.stat().st_size if path.exists() else 0
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            with index_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"offset": offset, "length": len(line.encode("utf-8"))}) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if segment_max_bytes is None and path.name == "timeline.ndjson":
                # Non-gateway resource timelines retain their previous bound;
                # foundation no longer imports a gateway retention policy.
                compact_indexed_ndjson(path, index_path, max_bytes=1024 * 1024,
                    preserve=lambda row: row.get("state") in {"completed", "failed", "cancelled", "rejected", "interrupted", "timed-out", "expired", "abandoned"})
    except Exception:  # noqa: BLE001
        logger.warning(
            "failed to record timeline event",
            extra={
                "component": component,
                "resource_kind": resource_kind,
                "resource_id": resource_id,
                "event": event,
                "path": str(path),
            },
            exc_info=True,
        )
    return record
