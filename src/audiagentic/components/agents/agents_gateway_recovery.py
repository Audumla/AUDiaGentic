"""Ownership-aware shared gateway recovery."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_store as store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryReport:
    examined: int = 0
    requeued: int = 0
    interrupted: int = 0
    cleared: int = 0
    skipped_live: int = 0


def _read_entry(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("discarding unreadable gateway active-work entry", extra={"entry": path.name})
        path.unlink(missing_ok=True)
        return None
    if not isinstance(value, dict):
        path.unlink(missing_ok=True)
        return None
    if not all(isinstance(value.get(key), str) and value[key] for key in ("request-id", "project-root")):
        path.unlink(missing_ok=True)
        return None
    return value


def recover_gateway_requests(service_root: Path, *, live_owner_epoch: str) -> RecoveryReport:
    """Recover stale work claimed by older service generations."""
    examined = requeued = interrupted = cleared = skipped_live = 0
    active_root = service_root / store.ACTIVE_WORK_DIR
    if not active_root.exists():
        return RecoveryReport()

    for entry in sorted(active_root.glob("*.json")):
        meta = _read_entry(entry)
        if meta is None:
            cleared += 1
            continue
        examined += 1
        request_id = meta["request-id"]
        project_root = Path(meta["project-root"])
        try:
            record = store.read_record(project_root, request_id)
        except Exception:  # noqa: BLE001
            logger.warning("gateway active-work entry points to unreadable request", extra={"request-id": request_id})
            continue

        if record["state"] in store.TERMINAL_STATES:
            store.clear_active_work(service_root, request_id)
            cleared += 1
            continue
        record_epoch = record.get("dispatch-owner-epoch")
        if record_epoch == live_owner_epoch:
            skipped_live += 1
            continue
        if not isinstance(record_epoch, str) or not record_epoch:
            store.clear_active_work(service_root, request_id)
            cleared += 1
            continue

        if record["state"] == "queued":
            store.release_stale_claim(project_root, request_id, stale_epoch=record_epoch)
            store.clear_active_work(service_root, request_id)
            requeued += 1
        elif record["state"] == "running":
            store.transition_recovered_terminal(
                project_root,
                request_id,
                "interrupted",
                error={
                    "code": "CON-AGW-084",
                    "kind": "agents",
                    "message": "owning service generation is gone",
                },
                stale_epoch=record_epoch,
            )
            store.clear_active_work(service_root, request_id)
            interrupted += 1

    return RecoveryReport(
        examined=examined,
        requeued=requeued,
        interrupted=interrupted,
        cleared=cleared,
        skipped_live=skipped_live,
    )
