"""Transition operations for the gateway store (SH18).

Owns all state-change operations: transitions, cancellations, claims, and
owned-mutation fencing. Imports _records (write/read records) and _admission
(record_gateway_timeline, _request_lock, active_work functions) — one-way
edges only.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_gateway_work_index import (
    clear_stale_terminal_index,
    update_work_index_phase,
    write_work_index_entry,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

from . import _shared
from ._admission import (
    clear_active_work,
    record_active_work,
)
from ._records import (
    _read_record_locked,
    _redact_error,
    write_record,
)
from ._shared import (
    _request_lock,
    record_gateway_timeline,
)

logger = logging.getLogger(__name__)

# SH07 crash-matrix test-only hook: widens the terminal-write-to-index-cleanup
# control-plane window so a real OS process kill can be observed landing
# inside it (the window is otherwise a single-thread gap between two adjacent
# calls with no I/O in between — too narrow to hit reliably from outside the
# process). No-op unless explicitly set; reading an unset env var costs
# nothing and changes no production behavior.
_ENV_TEST_STALL_TERMINAL_TO_CLEANUP_MS = "AUDIAGENTIC_GATEWAY_TEST_STALL_TERMINAL_TO_CLEANUP_MS"


def _test_stall_terminal_to_cleanup() -> None:
    raw = os.environ.get(_ENV_TEST_STALL_TERMINAL_TO_CLEANUP_MS)
    if not raw:
        return
    try:
        ms = int(raw)
    except ValueError:
        return
    if ms > 0:
        time.sleep(ms / 1000.0)


def ensure_transition(current_state: str, new_state: str) -> None:
    if not _shared.is_known_state_fn(current_state):
        raise AudiaGenticError(
            code="VAL-AGW-006",
            kind="agents",
            message="unknown gateway request state",
            details={"state": current_state},
        )
    if not _shared.transition_allowed_fn(current_state, new_state):
        raise AudiaGenticError(
            code="CON-AGW-001",
            kind="agents",
            message="illegal gateway request state transition",
            details={"from": current_state, "to": new_state},
        )


def transition_record(
    project_root: Path,
    request_id: str,
    new_state: str,
    *,
    updates: dict[str, Any] | None = None,
    expected_revision: int | None = None,
    expected_dispatch_owner_epoch: str | None = None,
    expected_worker_id: str | None = None,
    expected_attempt_epoch: int | None = None,
) -> dict[str, Any]:
    """Transition a request record to a new state and persist it.

    ``updates`` may set only the mutable result fields (provider-id,
    model-id, output, completion, usage, error, started-at, finished-at,
    session-id). Admission identity — context fingerprint, prompt digest,
    profile ID, idempotency key, owner/worker/attempt fencing — is immutable
    through this path (SH review C12); ownership mutation goes through its
    dedicated typed operations. ``error`` is redacted before persisting.
    """
    illegal = {
        key.replace("_", "-") for key in (updates or {})
    } - _shared._MUTABLE_RESULT_FIELDS
    if illegal:
        raise AudiaGenticError(
            code="VAL-AGW-098",
            kind="agents",
            message="request transition may not modify immutable admission/ownership fields",
            details={"request-id": request_id, "rejected-fields": sorted(illegal)},
        )
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=expected_revision,
            expected_dispatch_owner_epoch=expected_dispatch_owner_epoch,
            expected_worker_id=expected_worker_id,
            expected_attempt_epoch=expected_attempt_epoch,
        )
        ensure_transition(record["state"], new_state)
        updated = dict(record)
        updated["state"] = new_state
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        if updates:
            for key, value in updates.items():
                updated[key.replace("_", "-")] = _redact_error(value) if key in ("error",) else value
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "state.changed",
            state=new_state,
            attributes={
                "from": record["state"],
                "to": new_state,
                "updated-keys": sorted((updates or {}).keys()),
            },
        )
        return updated


def mark_cancel_requested(project_root: Path, request_id: str) -> dict[str, Any]:
    """Persist cancel-requested=true without changing state.

    Observable via read_record/wait/get_llm_request regardless of whether the
    in-process GatewayQueueManager that owns the running worker is still
    around — the flag survives independently of the in-memory cancel set.
    Idempotent.
    """
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record["cancel-requested"]:
            return record
        updated = dict(record)
        updated["cancel-requested"] = True
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "cancel.requested",
            state=updated["state"],
        )
        return updated


# Closed vocabulary: the only components that can genuinely observe a cancel
# intent. Arbitrary actor strings are rejected (SH review C10).
CANCEL_ACK_ACTORS = frozenset({"queue-worker", "session-runtime", "dispatch", "recovery"})


def acknowledge_cancel(project_root: Path, request_id: str, *, by: str) -> dict[str, Any]:
    """Record the first component that observed a cancel request.

    First writer wins so a later session/runtime acknowledgement cannot erase
    the recovery or queue evidence that actually won the race. Acknowledgement
    is only legal when cancellation was actually requested, and only from the
    closed actor vocabulary.
    """
    if by not in CANCEL_ACK_ACTORS:
        raise AudiaGenticError(
            code="VAL-AGW-086",
            kind="agents",
            message="cancel acknowledgement actor is required and must be a known component",
            details={"by": by, "allowed": sorted(CANCEL_ACK_ACTORS)},
        )
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if not record.get("cancel-requested"):
            raise AudiaGenticError(
                code="CON-AGW-086",
                kind="agents",
                message="cannot acknowledge a cancellation that was never requested",
                details={"request-id": request_id, "state": record["state"]},
            )
        if record.get("cancel-acknowledged-by"):
            return record
        updated = dict(record)
        updated["cancel-acknowledged-at"] = now_iso_z()
        updated["cancel-acknowledged-by"] = by
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "cancel.acknowledged",
            state=updated["state"],
            attributes={"by": by},
        )
        return updated


def append_attempt(
    project_root: Path,
    request_id: str,
    *,
    agent_profile_id: str,
    provider_id: str | None,
    model_id: str | None,
    state: str,
    error: BaseException | dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    expected_dispatch_owner_epoch: str | None = None,
    expected_worker_id: str | None = None,
    expected_attempt_epoch: int | None = None,
) -> dict[str, Any]:
    """Append an attempt entry (one per profile/provider try) without changing request state."""
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=None,
            expected_dispatch_owner_epoch=expected_dispatch_owner_epoch,
            expected_worker_id=expected_worker_id,
            expected_attempt_epoch=expected_attempt_epoch,
        )
        attempts = list(record.get("attempts") or [])
        attempts.append({
            "agent-profile-id": agent_profile_id,
            "provider-id": provider_id,
            "model-id": model_id,
            "state": state,
            "error": _redact_error(error),
            "started-at": started_at or now_iso_z(),
            "finished-at": finished_at,
            "worker-id": record["worker-id"],
            "attempt-epoch": record["attempt-epoch"],
        })
        updated = dict(record)
        updated["attempts"] = attempts
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "attempt.recorded",
            state=record["state"],
            attributes={
                "agent-profile-id": agent_profile_id,
                "provider-id": provider_id,
                "model-id": model_id,
                "attempt-state": state,
                "attempt-count": len(attempts),
                "error": _redact_error(error),
            },
        )
        return updated


def cancel_queued_or_mark_requested(project_root: Path, request_id: str) -> dict[str, Any]:
    """Linearize cancellation with the queued-to-running dispatch boundary.

    A queue thread can remove an item from its in-memory pending deque before
    it durably claims the request.  Cancelling in that interval must make the
    queued record terminal, not merely set an intent flag that no worker can
    observe after the deque entry disappears.  Once the record is running,
    preserve the established cooperative-cancellation behaviour instead.
    """
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record["state"] != "queued":
            if record["state"] == "running" and not record["cancel-requested"]:
                updated = dict(record)
                updated["cancel-requested"] = True
                updated["updated-at"] = now_iso_z()
                updated["revision"] = record["revision"] + 1
                write_record(project_root, updated)
                record_gateway_timeline(
                    project_root,
                    request_id,
                    "cancel.requested",
                    state=updated["state"],
                )
                return updated
            return record

        updated = dict(record)
        updated.update({
            "state": "cancelled",
            "cancel-requested": True,
            "cancel-acknowledged-at": now_iso_z(),
            "cancel-acknowledged-by": "queue-worker",
            "updated-at": now_iso_z(),
            "finished-at": now_iso_z(),
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "state.changed",
            state="cancelled",
            attributes={"from": "queued", "to": "cancelled", "updated-keys": []},
        )
        return updated


def release_stale_claim(project_root: Path, request_id: str, *, stale_epoch: str) -> dict[str, Any]:
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record.get("dispatch-owner-epoch") != stale_epoch:
            raise AudiaGenticError(
                code="CON-AGW-083",
                kind="agents",
                message="gateway request dispatch ownership changed",
                details={},
            )
        if record["state"] != "queued":
            raise AudiaGenticError(
                code="CON-AGW-083",
                kind="agents",
                message="gateway request is not a stale queued claim",
                details={"state": record["state"]},
            )
        updated = dict(record)
        updated.update({
            "dispatch-owner-epoch": None,
            "dispatch-claimed-at": None,
            "dispatch-service-root": None,
            "updated-at": now_iso_z(),
            "revision": record["revision"] + 1,
            "recovery": {"reason": "service-restart", "outcome": "resubmit-required"},
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "dispatch.claim.released",
            state="queued",
            attributes={"stale-owner-epoch": stale_epoch},
        )
        return updated


def transition_recovered_terminal(
    project_root: Path,
    request_id: str,
    new_state: str,
    *,
    error: BaseException | dict[str, Any] | None,
    stale_epoch: str | None = None,
    replay_required: bool | None = None,
    replay_reason: str | None = None,
) -> dict[str, Any]:
    """Terminalize a recovered request.

    When *stale_epoch* is provided (the normal path), the dispatch-owner-epoch
    on the record must match to prevent a stale claim from terminalizing a
    freshly-owned request.  When *stale_epoch* is ``None`` (admitted-but-unclaimed
    crash window), no ownership check is performed because there was never an
    owner to fence.
    """
    if new_state not in _shared.TERMINAL_STATES:
        raise AudiaGenticError("VAL-AGW-084", "agents", "recovered transition must be terminal", {})
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if stale_epoch is not None:
            rec_epoch = record.get("dispatch-owner-epoch")
            if rec_epoch != stale_epoch:
                raise AudiaGenticError(
                    code="CON-AGW-083",
                    kind="agents",
                    message="gateway request dispatch ownership changed",
                    details={},
                )
        ensure_transition(record["state"], new_state)
        timestamp = now_iso_z()
        updated = dict(record)
        recovery_outcome = "replay-required" if replay_required else "resubmit-required"
        recovery_meta: dict[str, str] = {"reason": "service-restart", "outcome": recovery_outcome}
        updated.update({
            "state": new_state,
            "error": _redact_error(error),
            "finished-at": timestamp,
            "dispatch-service-root": None,
            "updated-at": timestamp,
            "revision": record["revision"] + 1,
            "recovery": recovery_meta,
        })
        if replay_required is not None:
            updated["replay-required"] = replay_required
        if replay_reason is not None:
            updated["replay-reason"] = replay_reason
        if updated.get("cancel-requested") and not updated.get("cancel-acknowledged-by"):
            updated["cancel-acknowledged-at"] = timestamp
            updated["cancel-acknowledged-by"] = "recovery"
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "recovery.terminalized",
            state=new_state,
            attributes={"stale-owner-epoch": stale_epoch},
        )
        return updated


def start_attempt(project_root: Path, request_id: str, worker_id: str) -> dict[str, Any]:
    """Atomically assign a new worker/attempt epoch and enter running state."""
    if not worker_id:
        raise AudiaGenticError(
            code="VAL-AGW-070",
            kind="agents",
            message="worker_id is required",
            details={},
        )
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        ensure_transition(record["state"], "running")
        updated = dict(record)
        updated.update({
            "state": "running",
            "worker-id": worker_id,
            "attempt-epoch": record["attempt-epoch"] + 1,
            "started-at": now_iso_z(),
            "updated-at": now_iso_z(),
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "attempt.started",
            state="running",
            attributes={
                "worker-id": worker_id,
                "attempt-epoch": updated["attempt-epoch"],
                "context-fingerprint": updated.get("context-fingerprint"),
            },
        )
        return updated


def claim_dispatch(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    expected_revision: int,
    service_root: Path | None = None,
) -> dict[str, Any]:
    """Fence a queued request to one service owner before it starts work.

    Claiming is intentionally separate from starting a provider attempt: a
    service crash between them stays visibly queued-but-claimed, rather than
    looking as though execution definitely began.
    """
    if not owner_epoch:
        raise AudiaGenticError("VAL-AGW-083", "agents", "dispatch owner epoch is required", {})
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record["revision"] != expected_revision:
            raise AudiaGenticError(
                "CON-AGW-071", "agents", "gateway request revision changed",
                {"expected": expected_revision, "actual": record["revision"]},
            )
        if record["state"] != "queued":
            raise AudiaGenticError("CON-AGW-083", "agents", "gateway request is not available for dispatch claim", {})
        current_owner = record.get("dispatch-owner-epoch")
        if current_owner not in (None, owner_epoch):
            raise AudiaGenticError("CON-AGW-083", "agents", "gateway request dispatch ownership changed", {})
        if current_owner == owner_epoch:
            record_active_work(service_root, project_root, request_id, owner_epoch=owner_epoch)
            return record
        updated = dict(record)
        updated.update({
            "dispatch-owner-epoch": owner_epoch,
            "dispatch-claimed-at": now_iso_z(),
            "dispatch-service-root": str(service_root) if service_root is not None else None,
            "updated-at": now_iso_z(),
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_active_work(service_root, project_root, request_id, owner_epoch=owner_epoch)
        # C7: write work-index entry at claim time (admitted phase if index dir exists)
        if service_root is not None:
            lane_key = record.get("gateway-execution-lane-key") or None
            try:
                # If an "admitted" entry already exists (written at admission time),
                # transition to "claimed"; otherwise create fresh with "claimed".
                did_update = update_work_index_phase(
                    service_root, request_id,
                    from_phase="admitted", to_phase="claimed",
                    owner_epoch=owner_epoch,
                )
                if not did_update:
                    write_work_index_entry(
                        service_root, project_root, request_id,
                        phase="claimed", owner_epoch=owner_epoch, lane_key=lane_key,
                    )
            except OSError:
                logger.warning("work-index write failed at admission (non-fatal)", extra={"request-id": request_id})
        record_gateway_timeline(
            project_root, request_id, "dispatch.claimed", state="queued",
            attributes={"dispatch-owner-epoch": owner_epoch},
        )
        return updated


def start_owned_attempt(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Start an attempt only from a current owner claim and exact revision."""
    if not owner_epoch or not worker_id:
        raise AudiaGenticError("VAL-AGW-070", "agents", "owner epoch and worker_id are required", {})
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=expected_revision,
            expected_dispatch_owner_epoch=owner_epoch,
            expected_worker_id=None,
            expected_attempt_epoch=None,
        )
        ensure_transition(record["state"], "running")
        updated = dict(record)
        timestamp = now_iso_z()
        updated.update({
            "state": "running", "worker-id": worker_id,
            "attempt-epoch": record["attempt-epoch"] + 1,
            "started-at": timestamp, "updated-at": timestamp,
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        # C7: update work-index phase to running
        service_root_start = None
        stored_root = record.get("dispatch-service-root")
        if isinstance(stored_root, str) and stored_root:
            service_root_start = Path(stored_root)
        if service_root_start is not None:
            try:
                update_work_index_phase(
                    service_root_start, request_id,
                    from_phase="claimed", to_phase="running",
                    owner_epoch=owner_epoch,
                )
            except OSError:
                logger.warning("work-index phase update failed at start (non-fatal)", extra={"request-id": request_id})
        record_gateway_timeline(
            project_root, request_id, "attempt.started", state="running",
            attributes={
                "dispatch-owner-epoch": owner_epoch,
                "worker-id": worker_id,
                "attempt-epoch": updated["attempt-epoch"],
                "context-fingerprint": updated.get("context-fingerprint"),
            },
        )
        return updated


def append_owned_attempt(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    **kwargs: Any,
) -> dict[str, Any]:
    """Append evidence only while the same service/worker/attempt still owns it."""
    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    return append_attempt(
        project_root, request_id,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id,
        expected_attempt_epoch=attempt_epoch,
        **kwargs,
    )


def update_owned_running_session(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    session_id: str,
) -> dict[str, Any]:
    """Attach the live session id while the current attempt is still running.

    Keep-alive requests open their session before the first turn completes.
    Runtime diagnostics need that session id immediately, while the terminal
    result write remains responsible for final output/completion fields.
    """
    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    if not session_id:
        raise AudiaGenticError(
            "VAL-AGW-087",
            "agents",
            "session_id is required for a running session update",
            {},
        )
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=None,
            expected_dispatch_owner_epoch=owner_epoch,
            expected_worker_id=worker_id,
            expected_attempt_epoch=attempt_epoch,
        )
        if record["state"] != "running":
            raise AudiaGenticError(
                "CON-AGW-087",
                "agents",
                "gateway request is not running",
                {"request-id": request_id, "state": record["state"]},
            )
        if record.get("session-id") == session_id:
            return record
        updated = dict(record)
        updated["session-id"] = session_id
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "session.attached",
            state=updated["state"],
            attributes={"session-id": session_id},
        )
        return updated


def transition_owned_terminal(
    project_root: Path,
    request_id: str,
    new_state: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    updates: dict[str, Any] | None = None,
    service_root: Path | None = None,
) -> dict[str, Any]:
    """Write a terminal result only with the complete dispatch fence."""
    if new_state not in _shared.TERMINAL_STATES:
        raise AudiaGenticError("VAL-AGW-084", "agents", "owned transition must be terminal", {})
    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    updated = transition_record(
        project_root, request_id, new_state, updates=updates,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id,
        expected_attempt_epoch=attempt_epoch,
    )
    service_root_for_cleanup = service_root
    if service_root_for_cleanup is None:
        stored_root = updated.get("dispatch-service-root")
        service_root_for_cleanup = Path(stored_root) if isinstance(stored_root, str) and stored_root else None
    _test_stall_terminal_to_cleanup()
    # C7: best-effort non-throwing index cleanup after terminalization
    if service_root_for_cleanup is not None:
        try:
            clear_stale_terminal_index(service_root_for_cleanup, request_id)
        except Exception:  # noqa: BLE001
            logger.warning("work-index terminal cleanup failed (non-fatal)", extra={"request-id": request_id})
    clear_active_work(service_root_for_cleanup, request_id)
    return updated


def link_replay(
    project_root: Path,
    old_request_id: str,
    *,
    new_request_id: str,
) -> dict[str, Any]:
    """Link a new replay request to its interrupted predecessor.

    Sets ``replayed-by-request-id`` on the old record so a caller can trace
    the replay chain.  The old request is not re-executed — only the linkage
    metadata is updated.
    """
    with _request_lock(project_root, old_request_id):
        record = _read_record_locked(project_root, old_request_id)
        if record["state"] != "interrupted" or record.get("replay-required") is not True:
            raise AudiaGenticError(
                "CON-AGW-103",
                "agents",
                "can only link replay to an interrupted request requiring replay",
                {"request-id": old_request_id, "state": record["state"]},
            )
        updated = dict(record)
        updated["replayed-by-request-id"] = new_request_id
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            old_request_id,
            "replay.linked",
            state=record["state"],
            attributes={"new-request-id": new_request_id},
        )
        return updated


def _require_owned_identity(owner_epoch: str | None, worker_id: str | None, attempt_epoch: int) -> None:
    """Reject the ``None`` sentinel before it can weaken an owned mutation."""
    if not owner_epoch or not worker_id or attempt_epoch < 1:
        raise AudiaGenticError(
            "VAL-AGW-085",
            "agents",
            "owned mutation requires dispatch owner, worker, and attempt identity",
            {},
        )


def _check_expected_identity(
    record: dict[str, Any],
    *,
    expected_revision: int | None,
    expected_dispatch_owner_epoch: str | None,
    expected_worker_id: str | None,
    expected_attempt_epoch: int | None,
) -> None:
    if expected_revision is not None and record["revision"] != expected_revision:
        raise AudiaGenticError(
            code="CON-AGW-071",
            kind="agents",
            message="gateway request revision changed",
            details={"expected": expected_revision, "actual": record["revision"]},
        )
    if (
        expected_dispatch_owner_epoch is not None
        and record.get("dispatch-owner-epoch") != expected_dispatch_owner_epoch
    ):
        raise AudiaGenticError(
            code="CON-AGW-083",
            kind="agents",
            message="gateway request dispatch ownership changed",
            details={},
        )
    if expected_worker_id is not None and record["worker-id"] != expected_worker_id:
        raise AudiaGenticError(
            code="CON-AGW-072",
            kind="agents",
            message="gateway request worker ownership changed",
            details={},
        )
    if expected_attempt_epoch is not None and record["attempt-epoch"] != expected_attempt_epoch:
        raise AudiaGenticError(
            code="CON-AGW-073",
            kind="agents",
            message="gateway request attempt epoch changed",
            details={"expected": expected_attempt_epoch, "actual": record["attempt-epoch"]},
        )
