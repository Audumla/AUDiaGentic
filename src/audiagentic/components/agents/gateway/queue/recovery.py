"""Ownership-aware shared gateway recovery."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import work_index as work_index
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryReport:
    examined: int = 0
    replay_required: int = 0
    interrupted: int = 0
    cleared: int = 0
    skipped_live: int = 0
    quarantined: int = 0
    queued: tuple[tuple[Path, str], ...] = ()
    running: tuple[tuple[Path, str], ...] = ()
    deferred: tuple[tuple[Path, str], ...] = ()


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


def _takeover_stale_request(
    service_root: Path,
    project_root: Path,
    request_id: str,
    record_epoch: str | None = None,
    *,
    live_owner_epoch: str,
) -> tuple[str | None, tuple[Path, str] | None]:
    """Take over stale non-terminal work without changing request identity/state."""
    try:
        record = store.read_record(project_root, request_id)
    except Exception:  # noqa: BLE001
        logger.warning("gateway entry points to unreadable request", extra={"request-id": request_id})
        return None, None

    if record["state"] in store.TERMINAL_STATES:
        store.clear_active_work(service_root, request_id)
        work_index.clear_stale_terminal_index(service_root, request_id)
        return None, None

    if record["state"] not in {"queued", "running"}:
        return None, None
    if (
        record["state"] == "running"
        and record.get("provider-transport-kind") != "provider-session"
    ):
        # An isolated worker has no attach/resume seam.  Re-running its frozen
        # prompt after a gateway crash could duplicate an already-started
        # external side effect, so leave the request running and its original
        # ownership marker intact for explicit evidence-based recovery.
        logger.warning(
            "deferring stale worker request recovery because execution cannot be reattached",
            extra={"request-id": request_id},
        )
        return "deferred", (project_root, request_id)
    worker_id = f"recovery_{uuid.uuid4().hex[:16]}" if record["state"] == "running" else None
    try:
        updated = store.takeover_nonterminal_owner(
            project_root,
            request_id,
            expected_owner_epoch=record_epoch,
            new_owner_epoch=live_owner_epoch,
            new_worker_id=worker_id,
            handoff_id=(record.get("recovery") or {}).get("handoff-id") if isinstance(record.get("recovery"), dict) else None,
        )
    except AudiaGenticError as exc:
        # A prior generation may have committed the request half of takeover
        # before crashing. Treat the already-current owner as idempotent and
        # repair the remaining durable markers below; never overwrite a
        # different live owner.
        if exc.code != "CON-AGW-083":
            raise
        updated = store.read_record(project_root, request_id)
        if updated.get("dispatch-owner-epoch") != live_owner_epoch:
            raise
    try:
        work_index.takeover_owner(
            service_root,
            request_id,
            expected_owner_epoch=record_epoch,
            new_owner_epoch=live_owner_epoch,
        )
    except AudiaGenticError as exc:
        if exc.code != "CON-AGW-106":
            raise
        # The request record is the authoritative owner fence. A crash between
        # the two writes leaves an older index epoch; repair it under the
        # exclusive current service owner rather than losing the work item.
        work_index.takeover_owner(
            service_root,
            request_id,
            expected_owner_epoch=None,
            new_owner_epoch=live_owner_epoch,
        )
    # Keep the hashed active-work marker aligned as well. This write is
    # idempotent and lets the next generation recover after any later crash.
    store.record_active_work(
        service_root, project_root, request_id, owner_epoch=live_owner_epoch
    )
    return updated["state"], (project_root, request_id)


def recovery_runner(record: dict[str, Any]):
    """Rebuild the immutable runner from admission-time record facts."""
    import functools

    from audiagentic.components.agents.gateway import dispatch as _dispatch
    from audiagentic.components.agents.gateway.api import _resolve_provider_isolation_tier

    runtime = record.get("gateway-profile-runtime")
    if not isinstance(runtime, dict):
        raise ValueError("recovered request has no gateway profile runtime snapshot")
    provider_id = record.get("resolved-provider-id") or runtime.get("provider-id")
    if not isinstance(provider_id, str) or not provider_id:
        raise ValueError("recovered request has no resolved provider")
    provider_metadata = record.get("provider-metadata")
    unresolved_pending = (
        isinstance(provider_metadata, dict)
        and provider_metadata.get("unresolved-turn-pending") is True
    )
    return functools.partial(
        _dispatch.dispatch_request,
        dispatch_prompt="",
        preallocated_session_id=None,
        manifest_id=str(record.get("manifest-id") or "recovered"),
        context_fingerprint=str(record.get("context-fingerprint") or ""),
        component_profile="",
        provider_isolation_tier=_resolve_provider_isolation_tier(provider_id),
        worker_timeout_seconds=float(record.get("timeout-seconds") or 300.0),
        # A running CAS happens before the side-effect checkpoint. If the
        # process died before that checkpoint, the prompt is proven unsent and
        # may continue through the ordinary admission path. Observation-only
        # recovery is reserved for a durable pending checkpoint.
        resume_existing=bool(record.get("recovery-required")) and unresolved_pending,
    )


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
    recovered_queued: list[tuple[Path, str]] = []
    recovered_running: list[tuple[Path, str]] = []
    deferred: list[tuple[Path, str]] = []
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

            state, item = _takeover_stale_request(
                service_root, project_root, request_id, record_epoch,
                live_owner_epoch=live_owner_epoch,
            )
            if item is not None:
                if state == "queued":
                    recovered_queued.append(item)
                elif state == "running":
                    recovered_running.append(item)
                else:
                    deferred.append(item)

    # --- Path 2: work-index entries (C7: admission-before-claim gap) -------------
    index_entries, idx_quarantined = work_index.recover_work_index_entries(
        service_root, live_owner_epoch=live_owner_epoch,
    )
    quarantined += idx_quarantined

    for widx in index_entries:
        if widx.request_id in processed_request_ids:
            # Already handled via active-work path.  Keep the index entry as
            # the durable startup marker; the live owner must still schedule
            # the request after this discovery pass.
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

        state, item = _takeover_stale_request(
            service_root, project_root, widx.request_id,
            record_epoch if record_epoch else None,
            live_owner_epoch=live_owner_epoch,
        )
        if item is not None:
            if state == "queued":
                recovered_queued.append(item)
            elif state == "running":
                recovered_running.append(item)
            else:
                deferred.append(item)

    return RecoveryReport(
        examined=examined,
        replay_required=replay_required,
        interrupted=interrupted,
        cleared=cleared,
        skipped_live=skipped_live,
        quarantined=quarantined,
        queued=tuple(recovered_queued),
        running=tuple(recovered_running),
        deferred=tuple(deferred),
    )
