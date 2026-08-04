"""Ownership-aware shared gateway recovery."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import work_index as work_index
from audiagentic.components.agents.gateway.queue.queue import (
    _publish_lifecycle_event,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryReport:
    examined: int = 0
    replay_required: int = 0
    interrupted: int = 0
    cleared: int = 0
    skipped_live: int = 0
    quarantined: int = 0


def _quarantine_entry(path: Path, *, reason_code: str) -> None:
    """Move a malformed active-work entry to the quarantine subdirectory."""
    qdir = path.parent / "quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    import shutil  # noqa: PLC0414
    dest = qdir / f"{path.stem}_{reason_code}.json"
    try:
        shutil.move(str(path), str(dest))
    except OSError:
        logger.warning("quarantine move failed, unlinking", extra={"entry": path.name})
        path.unlink(missing_ok=True)


def _read_entry(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("quarantining unreadable gateway active-work entry", extra={"entry": path.name})
        _quarantine_entry(path, reason_code="unreadable")
        return None
    if not isinstance(value, dict):
        _quarantine_entry(path, reason_code="not-object")
        return None
    if not all(isinstance(value.get(key), str) and value[key] for key in ("request-id", "project-root")):
        _quarantine_entry(path, reason_code="missing-fields")
        return None
    return value


def _terminalize_stale_request(
    service_root: Path,
    project_root: Path,
    request_id: str,
    record_epoch: str | None = None,
) -> tuple[int, int]:
    """Terminalize a stale non-terminal request found by recovery.

    Returns (replay_required_count, interrupted_count).  -1 means the request
    was already terminal or otherwise handled, and no count increment occurred.
    """
    try:
        record = store.read_record(project_root, request_id)
    except Exception:  # noqa: BLE001
        logger.warning("gateway entry points to unreadable request", extra={"request-id": request_id})
        return -1, -1

    if record["state"] in store.TERMINAL_STATES:
        store.clear_active_work(service_root, request_id)
        work_index.clear_stale_terminal_index(service_root, request_id)
        return 0, 0

    if record["state"] == "queued":
        terminal = store.transition_recovered_terminal(
            project_root, request_id, "interrupted",
            error={
                "code": "CON-AGW-102",
                "kind": "agents",
                "message": "replay required after gateway recovery",
            },
            stale_epoch=record_epoch,
            replay_required=True,
            replay_reason="gateway-recovered-without-work-payload",
        )
        store.clear_active_work(service_root, request_id)
        work_index.clear_stale_terminal_index(service_root, request_id)
        _publish_lifecycle_event("interrupted", terminal)
        return 1, 0
    elif record["state"] == "running":
        terminal = store.transition_recovered_terminal(
            project_root, request_id, "interrupted",
            error={
                "code": "CON-AGW-084",
                "kind": "agents",
                "message": "owning service generation is gone",
            },
            stale_epoch=record_epoch,
        )
        store.clear_active_work(service_root, request_id)
        work_index.clear_stale_terminal_index(service_root, request_id)
        _publish_lifecycle_event("interrupted", terminal)
        return 0, 1
    return 0, 0


def recover_gateway_requests(service_root: Path, *, live_owner_epoch: str) -> RecoveryReport:
    """Recover stale work claimed by older service generations.

    Two discovery paths:
    1. Active-work entries (existing path, backward compatible).
    2. Work-index entries (C7: covers admission-before-claim crash window).
    Request IDs processed in path 1 are excluded from path 2 to avoid duplicates.
    """
    # Opportunistic bounded-retention sweep on the quarantine directory.
    # Expired quarantine entries are removed before recovery processing begins,
    # so stale forensic data does not accumulate unboundedly.
    work_index.clear_expired_quarantine_entries(service_root)

    examined = replay_required = interrupted = cleared = skipped_live = quarantined = 0
    processed_request_ids: set[str] = set()

    # --- Path 1: active-work entries (existing, hashed filenames) ---------------
    # Skip work-index entries (req_*.json) so they are only processed by Path 2.
    # Malformed files with any name are still discovered for quarantine.
    active_root = service_root / store.ACTIVE_WORK_DIR
    if active_root.exists():
        for entry in sorted(active_root.glob("*.json")):
            if entry.name.startswith("req_"):
                continue  # work-index entry, handled by Path 2
            meta = _read_entry(entry)
            if meta is None:
                quarantined += 1
                continue
            examined += 1
            request_id = meta["request-id"]
            processed_request_ids.add(request_id)
            project_root = Path(meta["project-root"])

            try:
                record = store.read_record(project_root, request_id)
            except Exception:  # noqa: BLE001
                logger.warning("gateway active-work entry points to unreadable request", extra={"request-id": request_id})
                continue

            if record["state"] in store.TERMINAL_STATES:
                store.clear_active_work(service_root, request_id)
                work_index.clear_stale_terminal_index(service_root, request_id)
                cleared += 1
                continue
            record_epoch = record.get("dispatch-owner-epoch")
            if record_epoch == live_owner_epoch:
                skipped_live += 1
                continue
            if not isinstance(record_epoch, str) or not record_epoch:
                store.clear_active_work(service_root, request_id)
                work_index.clear_stale_terminal_index(service_root, request_id)
                cleared += 1
                continue

            rr, it = _terminalize_stale_request(service_root, project_root, request_id, record_epoch)
            if rr > 0:
                replay_required += rr
            if it > 0:
                interrupted += it

    # --- Path 2: work-index entries (C7: admission-before-claim gap) -------------
    index_entries, idx_quarantined = work_index.recover_work_index_entries(
        service_root, live_owner_epoch=live_owner_epoch,
    )
    quarantined += idx_quarantined

    for widx in index_entries:
        if widx.request_id in processed_request_ids:
            # Already handled via active-work path; clear the index entry.
            work_index.clear_work_index_entry(service_root, widx.request_id)
            continue

        examined += 1
        project_root = widx.project_root
        record_epoch = None

        try:
            record = store.read_record(project_root, widx.request_id)
        except Exception:  # noqa: BLE001
            # Missing or unreadable request referenced by index → quarantine.
            work_index.quarantine_work_index_entry(
                service_root,
                work_index._entry_path(service_root, widx.request_id),
                reason_code="missing-request",
            )
            quarantined += 1
            continue

        if record["state"] in store.TERMINAL_STATES:
            work_index.clear_work_index_entry(service_root, widx.request_id)
            cleared += 1
            continue

        # Determine the epoch for terminalization.
        if widx.owner_epoch:
            record_epoch = widx.owner_epoch
        else:
            record_epoch = record.get("dispatch-owner-epoch")

        if record_epoch and record_epoch == live_owner_epoch:
            skipped_live += 1
            continue

        # C7: admitted-but-unclaimed entries have no owner epoch.  They are
        # stale (the owning service generation is gone) and must be terminalized
        # as replay-required, not cleared silently.  Pass None for stale_epoch
        # so transition_recovered_terminal skips ownership fencing.
        rr, it = _terminalize_stale_request(service_root, project_root, widx.request_id, record_epoch if record_epoch else None)
        if rr > 0:
            replay_required += rr
        if it > 0:
            interrupted += it

    return RecoveryReport(
        examined=examined,
        replay_required=replay_required,
        interrupted=interrupted,
        cleared=cleared,
        skipped_live=skipped_live,
        quarantined=quarantined,
    )
