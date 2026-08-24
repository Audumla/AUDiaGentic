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

from audiagentic.components.agents.gateway.queue.work_index import (
    clear_stale_terminal_index,
    update_work_index_phase,
    write_work_index_entry,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service_contracts import add_seconds
from audiagentic.foundation.time import now_iso_z
from audiagentic.components.agents.gateway.diagnostics import (
    classify_error,
    evidence_from_activity,
    merge_diagnostics,
)

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
    extract_worker_evidence,
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
    illegal = {key.replace("_", "-") for key in (updates or {})} - _shared._MUTABLE_RESULT_FIELDS
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
                if key == "error":
                    # Extract bounded worker diagnostic evidence BEFORE
                    # redaction strips it (SH21 RV769 — private operator
                    # evidence for INT-AGW-076 failures).
                    evidence = extract_worker_evidence(value)
                    if evidence is not None:
                        updated["worker-evidence"] = evidence
                    updated[key.replace("_", "-")] = _redact_error(value)
                else:
                    updated[key.replace("_", "-")] = value
            if "error" in updates and updates.get("error") is not None:
                # Keep semantic diagnostics alongside the redacted public
                # error.  The provider code is evidence; this classification
                # is the gateway-owned recovery contract.
                updated["diagnostics"] = merge_diagnostics(
                    record.get("diagnostics"),
                    classify_error(updates.get("error")),
                )
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


def update_diagnostics(
    project_root: Path,
    request_id: str,
    diagnostics: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """CAS-update the diagnostic rollup without changing lifecycle state."""
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if expected_revision is not None and record.get("revision") != expected_revision:
            raise AudiaGenticError(
                code="CON-AGW-143",
                kind="agents",
                message="diagnostic recovery revision is stale",
                details={"request-id": request_id},
            )
        updated = dict(record)
        updated["diagnostics"] = merge_diagnostics(record.get("diagnostics"), diagnostics)
        if evidence is not None:
            updated["diagnostic-evidence"] = (
                list(record.get("diagnostic-evidence") or []) + [dict(evidence)]
            )[-8:]
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "diagnostics.updated",
            state=record.get("state"),
            attributes={"classification": diagnostics.get("classification"), "phase": diagnostics.get("phase")},
        )
        return updated


def mark_cancel_requested(
    project_root: Path,
    request_id: str,
    *,
    source: str = "api",
    actor_type: str = "client",
    actor_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Persist cancel-requested=true without changing state.

    Observable via read_record/wait/get_execution_request regardless of whether the
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
        updated["diagnostics"] = classify_error(
            {"code": "CON-AGW-CANCELLED"},
            phase="cancellation",
            side_effect_state=(record.get("diagnostics") or {}).get("side-effect-state")
            if isinstance(record.get("diagnostics"), dict)
            else None,
        )
        updated["cancel-provenance"] = {
            "source": source if source in {"api", "operator", "watchdog", "worker-shutdown", "system", "unknown-legacy"} else "unknown-legacy",
            "actor-type": actor_type if actor_type in {"client", "operator", "worker", "system", "unknown"} else "unknown",
            "actor-id": actor_id[:128] if isinstance(actor_id, str) else None,
            "reason": reason[:256] if isinstance(reason, str) else None,
            "requested-at": now_iso_z(),
        }
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
    execution_profile_id: str,
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
        attempts.append(
            {
                "execution-profile-id": execution_profile_id,
                "provider-id": provider_id,
                "model-id": model_id,
                "state": state,
                "error": _redact_error(error),
                "started-at": started_at or now_iso_z(),
                "finished-at": finished_at,
                "worker-id": record["worker-id"],
                "attempt-epoch": record["attempt-epoch"],
            }
        )
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
                "execution-profile-id": execution_profile_id,
                "provider-id": provider_id,
                "model-id": model_id,
                "attempt-state": state,
                "attempt-count": len(attempts),
                "error": _redact_error(error),
            },
        )
        return updated


def cancel_queued_or_mark_requested(
    project_root: Path,
    request_id: str,
    *,
    source: str = "queue-worker",
    actor_type: str = "worker",
    actor_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
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
                updated["diagnostics"] = classify_error(
                    {"code": "CON-AGW-CANCELLED"}, phase="cancellation",
                    side_effect_state=(record.get("diagnostics") or {}).get("side-effect-state")
                    if isinstance(record.get("diagnostics"), dict) else None,
                )
                updated["cancel-provenance"] = {
                    "source": source if source in {"api", "operator", "watchdog", "worker-shutdown", "system", "unknown-legacy"} else "unknown-legacy",
                    "actor-type": actor_type if actor_type in {"client", "operator", "worker", "system", "unknown"} else "unknown",
                    "actor-id": actor_id[:128] if isinstance(actor_id, str) else None,
                    "reason": reason[:256] if isinstance(reason, str) else None,
                    "requested-at": now_iso_z(),
                }
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
        updated.update(
            {
                "state": "cancelled",
                "cancel-requested": True,
                "diagnostics": classify_error(
                    {"code": "CON-AGW-CANCELLED"}, phase="cancellation",
                    side_effect_state=(record.get("diagnostics") or {}).get("side-effect-state")
                    if isinstance(record.get("diagnostics"), dict) else None,
                ),
                "cancel-provenance": {
                    "source": source if source in {"api", "operator", "watchdog", "worker-shutdown", "system", "unknown-legacy"} else "unknown-legacy",
                    "actor-type": actor_type if actor_type in {"client", "operator", "worker", "system", "unknown"} else "unknown",
                    "actor-id": actor_id[:128] if isinstance(actor_id, str) else None,
                    "reason": reason[:256] if isinstance(reason, str) else None,
                    "requested-at": now_iso_z(),
                },
                "cancel-acknowledged-at": now_iso_z(),
                "cancel-acknowledged-by": "queue-worker",
                "updated-at": now_iso_z(),
                "finished-at": now_iso_z(),
                "revision": record["revision"] + 1,
            }
        )
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
        updated.update(
            {
                "dispatch-owner-epoch": None,
                "dispatch-claimed-at": None,
                "dispatch-service-root": None,
                "updated-at": now_iso_z(),
                "revision": record["revision"] + 1,
                "recovery": {"reason": "service-restart", "outcome": "resubmit-required"},
            }
        )
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
        # Extract worker evidence before redaction (SH21 RV769).
        recovered_evidence = extract_worker_evidence(error)
        updated.update(
            {
                "state": new_state,
                "error": _redact_error(error),
                "finished-at": timestamp,
                "dispatch-service-root": None,
                "updated-at": timestamp,
                "revision": record["revision"] + 1,
                "recovery": recovery_meta,
                # Terminal: the watchdog no longer applies, and a leftover
                # "active" state would falsely suggest still-running work.
                "watchdog-state": "not-started",
                "watchdog-reason": None,
            }
        )
        if recovered_evidence is not None:
            updated["worker-evidence"] = recovered_evidence
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
        updated.update(
            {
                "state": "running",
                "worker-id": worker_id,
                "attempt-epoch": record["attempt-epoch"] + 1,
                "started-at": now_iso_z(),
                "updated-at": now_iso_z(),
                "revision": record["revision"] + 1,
            }
        )
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
                "CON-AGW-071",
                "agents",
                "gateway request revision changed",
                {"expected": expected_revision, "actual": record["revision"]},
            )
        if record["state"] != "queued":
            raise AudiaGenticError(
                "CON-AGW-083", "agents", "gateway request is not available for dispatch claim", {}
            )
        current_owner = record.get("dispatch-owner-epoch")
        if current_owner not in (None, owner_epoch):
            raise AudiaGenticError(
                "CON-AGW-083", "agents", "gateway request dispatch ownership changed", {}
            )
        if current_owner == owner_epoch:
            record_active_work(service_root, project_root, request_id, owner_epoch=owner_epoch)
            return record
        updated = dict(record)
        updated.update(
            {
                "dispatch-owner-epoch": owner_epoch,
                "dispatch-claimed-at": now_iso_z(),
                "dispatch-service-root": str(service_root) if service_root is not None else None,
                "updated-at": now_iso_z(),
                "revision": record["revision"] + 1,
            }
        )
        write_record(project_root, updated)
        record_active_work(service_root, project_root, request_id, owner_epoch=owner_epoch)
        # C7: write work-index entry at claim time (admitted phase if index dir exists)
        if service_root is not None:
            lane_key = record.get("gateway-execution-lane-key") or None
            try:
                # If an "admitted" entry already exists (written at admission time),
                # transition to "claimed"; otherwise create fresh with "claimed".
                did_update = update_work_index_phase(
                    service_root,
                    request_id,
                    from_phase="admitted",
                    to_phase="claimed",
                    owner_epoch=owner_epoch,
                )
                if not did_update:
                    write_work_index_entry(
                        service_root,
                        project_root,
                        request_id,
                        phase="claimed",
                        owner_epoch=owner_epoch,
                        lane_key=lane_key,
                    )
            except OSError:
                logger.warning(
                    "work-index write failed at admission (non-fatal)",
                    extra={"request-id": request_id},
                )
        record_gateway_timeline(
            project_root,
            request_id,
            "dispatch.claimed",
            state="queued",
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
        raise AudiaGenticError(
            "VAL-AGW-070", "agents", "owner epoch and worker_id are required", {}
        )
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
        updated.update(
            {
                "state": "running",
                "worker-id": worker_id,
                "attempt-epoch": record["attempt-epoch"] + 1,
                "started-at": timestamp,
                "updated-at": timestamp,
                "revision": record["revision"] + 1,
            }
        )
        write_record(project_root, updated)
        # C7: update work-index phase to running
        service_root_start = None
        stored_root = record.get("dispatch-service-root")
        if isinstance(stored_root, str) and stored_root:
            service_root_start = Path(stored_root)
        if service_root_start is not None:
            try:
                update_work_index_phase(
                    service_root_start,
                    request_id,
                    from_phase="claimed",
                    to_phase="running",
                    owner_epoch=owner_epoch,
                )
            except OSError:
                logger.warning(
                    "work-index phase update failed at start (non-fatal)",
                    extra={"request-id": request_id},
                )
        record_gateway_timeline(
            project_root,
            request_id,
            "attempt.started",
            state="running",
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
        project_root,
        request_id,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id,
        expected_attempt_epoch=attempt_epoch,
        **kwargs,
    )


def renew_owned_activity(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    activity_seq: int,
    activity_source: str,
    activity_lease_seconds: float,
) -> dict[str, Any]:
    """Persist one accepted activity renewal under current attempt fencing.

    Gateway receipt time is authoritative; worker clocks and provider payloads
    never enter the record. Duplicate/out-of-order sequence numbers are an
    idempotent no-op, while an owner/worker/attempt mismatch fails closed.
    """
    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    if isinstance(activity_seq, bool) or not isinstance(activity_seq, int) or activity_seq <= 0:
        raise AudiaGenticError("VAL-AGW-088", "agents", "activity sequence must be positive", {})
    if not isinstance(activity_source, str) or not activity_source:
        raise AudiaGenticError("VAL-AGW-088", "agents", "activity source is required", {})
    if isinstance(activity_lease_seconds, bool) or activity_lease_seconds <= 0:
        raise AudiaGenticError("VAL-AGW-088", "agents", "activity lease seconds must be positive", {})
    return record_owned_activity(
        project_root,
        request_id,
        owner_epoch=owner_epoch,
        worker_id=worker_id,
        attempt_epoch=attempt_epoch,
        kind="owner-heartbeat",
        source=activity_source,
        source_instance=worker_id,
        source_sequence=activity_seq,
        activity_lease_seconds=activity_lease_seconds,
        aggregate_sequence=activity_seq,
    )


def record_owned_activity(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    kind: str,
    source: str,
    source_instance: str | None = None,
    source_sequence: int | None = None,
    phase: str | None = None,
    provider_capability: str | None = None,
    activity_lease_seconds: float = 300.0,
    aggregate_sequence: int | None = None,
) -> dict[str, Any]:
    """Accept provider or owner activity and allocate aggregate sequence.

    The aggregate sequence is allocated while holding the request mutation
    lock. Provider/source sequence values are only dedupe cursors inside their
    source namespace and can restart on a new worker/session attempt.
    """
    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    if kind not in {"provider", "owner-heartbeat"}:
        raise AudiaGenticError("VAL-AGW-088", "agents", "unknown activity kind", {"kind": kind})
    if not isinstance(source, str) or not source:
        raise AudiaGenticError("VAL-AGW-088", "agents", "activity source is required", {})
    if source_sequence is not None and (isinstance(source_sequence, bool) or not isinstance(source_sequence, int) or source_sequence < 0):
        raise AudiaGenticError("VAL-AGW-088", "agents", "source activity sequence is invalid", {})
    if activity_lease_seconds <= 0:
        raise AudiaGenticError("VAL-AGW-088", "agents", "activity lease seconds must be positive", {})
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
            raise AudiaGenticError("CON-AGW-088", "agents", "gateway request is not running", {})
        activity = record.get("activity")
        if not isinstance(activity, dict):
            activity = _shared.default_activity()
        bucket_name = "provider" if kind == "provider" else "owner"
        bucket = dict(activity.get(bucket_name) or {})
        if (
            source_sequence is not None
            and bucket.get("source-instance") == source_instance
            and source_sequence <= int(bucket.get("source-sequence") or 0)
        ):
            return record
        received_at = now_iso_z()
        aggregate = aggregate_sequence if aggregate_sequence is not None else int(activity.get("sequence") or record.get("activity-sequence") or 0) + 1
        bucket.update({
            "last-at": received_at,
            "lease-expires-at": add_seconds(received_at, activity_lease_seconds),
            "source": source,
            "source-instance": source_instance,
            "source-sequence": source_sequence if source_sequence is not None else int(bucket.get("source-sequence") or 0) + 1,
        })
        if kind == "provider":
            bucket["phase"] = phase
            if provider_capability in {"unsupported", "supported", "unknown"}:
                bucket["capability"] = provider_capability
        activity.update({"sequence": aggregate, "last-at": received_at, "last-source": source, bucket_name: bucket})
        updated = dict(record)
        evidence_items = list(record.get("diagnostic-evidence") or [])
        evidence_items.append(
            evidence_from_activity(
                request_id=request_id,
                session_id=record.get("session-id"),
                attempt_epoch=attempt_epoch,
                phase=phase,
                source=source,
                source_sequence=source_sequence,
                activity_sequence=aggregate,
            )
        )
        updated["diagnostic-evidence"] = evidence_items[-8:]
        diagnostics = record.get("diagnostics")
        if isinstance(diagnostics, dict):
            diagnostics = dict(diagnostics)
            diagnostics["coalesced-observation-count"] = int(
                diagnostics.get("coalesced-observation-count") or 0
            ) + 1
            diagnostics["evidence-count"] = int(diagnostics.get("evidence-count") or 0) + 1
            updated["diagnostics"] = diagnostics
        updated.update(
            {
                "last-activity-at": received_at,
                "activity-sequence": aggregate,
                "activity-source": source,
                "activity-lease-expires-at": add_seconds(received_at, activity_lease_seconds),
                "activity": activity,
                "watchdog-state": "active",
                "watchdog-reason": "verified-activity-renewed",
                "updated-at": received_at,
                "revision": record["revision"] + 1,
            }
        )
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "activity.renewed",
            state="running",
            attributes={"activity-sequence": aggregate, "activity-source": source, "activity-kind": kind},
        )
        return updated


def mark_watchdog_intervention_if_expired(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
) -> dict[str, Any]:
    """Record a non-terminal diagnostic when an owned activity lease expires.

    Lease expiry is only a suspicion signal: this transition never fails or
    interrupts the request. Positive death evidence remains the sole route to
    terminal recovery. The owner/worker/attempt fence prevents stale monitors
    from annotating a successor attempt.
    """
    from datetime import datetime, timezone

    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
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
            return record
        activity = record.get("activity") if isinstance(record.get("activity"), dict) else {}
        provider = activity.get("provider") if isinstance(activity.get("provider"), dict) else {}
        # A provider stall is meaningful only when the provider advertises a
        # liveness capability and has emitted evidence. Otherwise retain the
        # legacy owner-lease diagnostic (useful for older records).
        if provider.get("capability") == "unsupported":
            return record
        expiry = provider.get("lease-expires-at") if provider.get("capability") == "supported" and provider.get("last-at") else record.get("activity-lease-expires-at")
        if not isinstance(expiry, str) or not expiry:
            return record
        try:
            expired = datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
        except ValueError:
            expired = False
        if not expired or record.get("watchdog-state") == "intervention":
            return record
        timestamp = now_iso_z()
        updated = dict(record)
        diagnostics = classify_error(
            {"code": "TO-AGW-076", "details": {"failure-reason": "activity-lease-expired"}},
            phase="reconciliation",
            side_effect_state="may-have-started",
        )
        prior = record.get("diagnostics")
        if isinstance(prior, dict):
            diagnostics["evidence-count"] = int(prior.get("evidence-count") or 0) + 1
            diagnostics["coalesced-observation-count"] = int(
                prior.get("coalesced-observation-count") or 0
            )
        updated["diagnostics"] = diagnostics
        updated["diagnostic-evidence"] = (
            list(record.get("diagnostic-evidence") or [])
            + [{
                "evidence-id": f"ev_watchdog_{attempt_epoch}",
                "sequence": int(record.get("activity-sequence") or 0),
                "request-id": request_id,
                "session-id": record.get("session-id"),
                "attempt-epoch": attempt_epoch,
                "phase": "reconciliation",
                "kind": "activity-lease-expired",
                "certainty": "weak",
                "side-effect-state": "may-have-started",
                "source": "gateway-watchdog",
                "source-sequence": None,
            }]
        )[-8:]
        updated.update({
            "watchdog-state": "intervention",
            "watchdog-reason": "activity-lease-expired-diagnostic",
            "updated-at": timestamp,
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_gateway_timeline(project_root, request_id, "activity.lease-expired-diagnostic", state="running", attributes={"attempt-epoch": attempt_epoch})
        return updated


def update_owned_running_session(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    session_id: str,
    provider_metadata: dict[str, Any] | None = None,
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
        if record.get("session-id") == session_id and provider_metadata is None:
            return record
        updated = dict(record)
        updated["session-id"] = session_id
        if provider_metadata is not None:
            updated["provider-metadata"] = dict(provider_metadata)
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
    terminal_updates = dict(updates or {})
    error = terminal_updates.get("error")
    if isinstance(error, dict):
        details = error.get("details")
        classification = details.get("watchdog-classification") if isinstance(details, dict) else None
        if isinstance(classification, str) and classification:
            terminal_updates["terminal-classification"] = classification
    # The watchdog only monitors a request while it is running; once
    # terminal, a leftover "active"/"intervention" state is stale and
    # falsely suggests the request is still being worked on.
    terminal_updates["watchdog-state"] = "not-started"
    terminal_updates["watchdog-reason"] = None
    updated = transition_record(
        project_root,
        request_id,
        new_state,
        updates=terminal_updates,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id,
        expected_attempt_epoch=attempt_epoch,
    )
    service_root_for_cleanup = service_root
    if service_root_for_cleanup is None:
        stored_root = updated.get("dispatch-service-root")
        service_root_for_cleanup = (
            Path(stored_root) if isinstance(stored_root, str) and stored_root else None
        )
    _test_stall_terminal_to_cleanup()
    # C7: best-effort non-throwing index cleanup after terminalization
    if service_root_for_cleanup is not None:
        try:
            clear_stale_terminal_index(service_root_for_cleanup, request_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "work-index terminal cleanup failed (non-fatal)", extra={"request-id": request_id}
            )
    clear_active_work(service_root_for_cleanup, request_id)
    return updated


def bind_and_start_owned_attempt(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    expected_revision: int,
    resolved_source_id: str,
    resolved_model_id: str,
    resolved_capacity_generation: str | None = None,
) -> dict[str, Any]:
    """Atomically bind an owned queued request to a source and start it.

    A scheduler must reserve capacity before calling this function, then pass
    the exact selected source/model. The same request lock verifies ownership
    and revision, records that durable binding, and changes state to running;
    therefore no provider invocation can observe an unpersisted placement.
    On a fencing failure no binding is written, so the caller can release its
    reservation safely.
    """
    if not owner_epoch or not worker_id:
        raise AudiaGenticError(
            "VAL-AGW-070", "agents", "owner epoch and worker_id are required", {}
        )
    if not resolved_source_id or not resolved_model_id:
        raise AudiaGenticError(
            "VAL-AGW-086",
            "agents",
            "resolved source id and model id are required before dispatch",
            {},
        )
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
        timestamp = now_iso_z()
        updated = dict(record)
        updated.update(
            {
                "state": "running",
                "worker-id": worker_id,
                "attempt-epoch": record["attempt-epoch"] + 1,
                "resolved-source-id": resolved_source_id,
                "resolved-model-id": resolved_model_id,
                "resolved-capacity-generation": resolved_capacity_generation,
                "watchdog-state": "active",
                "watchdog-reason": "awaiting-verified-activity",
                "started-at": timestamp,
                "updated-at": timestamp,
                "revision": record["revision"] + 1,
            }
        )
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "dispatch.bound-and-started",
            state="running",
            attributes={
                "dispatch-owner-epoch": owner_epoch,
                "worker-id": worker_id,
                "attempt-epoch": updated["attempt-epoch"],
                "resolved-source-id": resolved_source_id,
                "resolved-model-id": resolved_model_id,
                "resolved-capacity-generation": resolved_capacity_generation,
            },
        )
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
        if record["state"] != "interrupted" or not record.get("replay-required"):  # noqa: SIM401
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


def _require_owned_identity(
    owner_epoch: str | None, worker_id: str | None, attempt_epoch: int
) -> None:
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
