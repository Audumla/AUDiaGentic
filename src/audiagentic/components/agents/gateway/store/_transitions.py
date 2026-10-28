"""Transition operations for the gateway store (SH18).

Owns all state-change operations: transitions, cancellations, claims, and
owned-mutation fencing. Imports _records (write/read records) and _admission
(record_gateway_timeline, _request_lock, active_work functions) — one-way
edges only.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway.diagnostics import (
    activity_group,
    classify_error,
    evidence_from_activity,
    merge_diagnostics,
    normalize_activity_label,
    stale_progress_diagnostic,
)
from audiagentic.components.agents.gateway.queue.work_index import (
    clear_stale_terminal_index,
    update_work_index_phase,
    write_work_index_entry,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service_contracts import add_seconds
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import is_meaningful_activity

from . import _shared
from ._admission import (
    clear_active_work,
    record_active_work,
)
from ._records import (
    _read_record_locked,
    _redact_error,
    bounded_recovery_error,
    write_record,
)
from ._shared import (
    _request_lock,
    extract_worker_evidence,
    record_gateway_timeline,
)

logger = logging.getLogger(__name__)
_recovery_trace_lock = threading.Lock()
_recovery_trace_failures = 0


def recovery_trace_failure_count() -> int:
    """Process-local diagnostic drops, never request or effect state."""
    with _recovery_trace_lock:
        return _recovery_trace_failures

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


def _apply_terminal_finalization(
    project_root: Path,
    request_id: str,
    finalization: Mapping[str, Any],
) -> bool:
    """Apply idempotent session cleanup after a terminal capture.

    The request record carries the finalization marker, so a process crash
    between the request write and this cross-record update can be replayed by
    the next status read.  A newer unresolved turn owns the session and makes
    this cleanup obsolete; in that case it is safely skipped.
    """
    session_id = finalization.get("session-id")
    if not isinstance(session_id, str) or not session_id:
        return True
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    session_record = session_store.read_session_record(project_root, session_id)
    metadata = session_store.session_provider_metadata(session_record)
    unresolved_turn_id = metadata.get("unresolved-turn-id")
    if unresolved_turn_id not in {None, request_id}:
        return True
    expected_checkpoint = finalization.get("pre-clear-checkpoint")
    if not isinstance(expected_checkpoint, dict):
        expected_checkpoint = None
    if "expected-session-binding" in finalization and session_record.get("binding") != finalization["expected-session-binding"]:
        return False
    if unresolved_turn_id is None and metadata.get("unresolved-turn-pending") is False:
        # A crash can occur after session clear but before memory handoff.
        # Surviving residue must still agree; never overwrite a newer attempt.
        if expected_checkpoint is not None and any(
            key in metadata and metadata[key] != expected_checkpoint.get(key)
            for key in session_store._RECOVERY_CHECKPOINT_KEYS
            - {"unresolved-turn-pending", "recovery-state"}
        ):
            return False
        return True
    binding = finalization.get("recovered-binding")
    if isinstance(binding, dict) and binding and not finalization.get("clear-unresolved-turn"):
        session_store.update_provider_metadata(
            project_root,
            session_id,
            {str(key): value for key, value in binding.items() if value is not None},
        )
    if finalization.get("clear-unresolved-turn"):
        return session_store._clear_terminal_submission_checkpoint_locked(
            project_root,
            session_id,
            request_id,
            recovery_state="terminal-captured",
            expected_metadata=expected_checkpoint,
            expected_binding=finalization.get("expected-session-binding"),
            check_binding="expected-session-binding" in finalization,
            binding_metadata_update=(
                {str(key): value for key, value in binding.items() if value is not None}
                if isinstance(binding, dict) else None
            ),
            remove_keys=tuple(
                key for key in session_store.TERMINAL_SUBMISSION_CHECKPOINT_REMOVE_KEYS
                if key != "recovery-state"
            ),
        )
    return True


def repair_pending_terminal_finalization(project_root: Path, request_id: str) -> bool:
    """Replay a terminal session cleanup marker, if one was left by a crash."""
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        finalization = record.get("terminal-finalization")
        if record.get("state") != "completed" or not isinstance(finalization, dict):
            return False
        try:
            if not _apply_terminal_finalization(project_root, request_id, finalization):
                return False
        except Exception:  # noqa: BLE001 - leave marker for the next status read
            logger.warning(
                "terminal session finalization replay deferred",
                extra={"request-id": request_id},
                exc_info=True,
            )
            return False
        # A captured private checkpoint remains replayable until the matching
        # live observer/memory handoff acknowledges it outside these locks.
        if "pre-clear-checkpoint" not in finalization:
            updated = dict(record)
            updated.pop("terminal-finalization", None)
            updated["updated-at"] = now_iso_z()
            updated["revision"] = record["revision"] + 1
            write_record(project_root, updated)
            record_gateway_timeline(
                project_root, request_id, "session.finalization-replayed", state="completed",
                attributes={"source": "status-replay"},
            )
            return True
    # Never call into the live event loop while holding a file mutation lock:
    # its observer may itself be waiting to publish a fenced checkpoint.
    from ..session.capture_handoff import reconcile_idle_captured_handoff
    return reconcile_idle_captured_handoff(project_root, request_id)


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
    _request_lock_held: bool = False,
) -> dict[str, Any]:
    """Transition a request record to a new state and persist it.

    ``updates`` may set only the mutable result fields (provider-id,
    model-id, output, completion, usage, error, started-at, finished-at,
    session-id). Admission identity — context fingerprint, prompt digest,
    profile ID, idempotency key, owner/worker/attempt fencing — is immutable
    through this path (SH review C12); ownership mutation goes through its
    dedicated typed operations. ``error`` is redacted before persisting.

    Internal publication coordinators may pass ``_request_lock_held=True``
    while holding this exact request lock. They must perform worker-session
    finalization only after releasing their outer lock.
    """
    illegal = {key.replace("_", "-") for key in (updates or {})} - _shared._MUTABLE_RESULT_FIELDS
    if illegal:
        raise AudiaGenticError(
            code="VAL-AGW-098",
            kind="agents",
            message="request transition may not modify immutable admission/ownership fields",
            details={"request-id": request_id, "rejected-fields": sorted(illegal)},
        )
    with nullcontext() if _request_lock_held else _request_lock(project_root, request_id):
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
            # An explicit diagnostics update carries the gateway-owned
            # disposition and must win over error-derived classification.
            if "diagnostics" in updates:
                updated["diagnostics"] = updates["diagnostics"]
        if new_state in _shared.TERMINAL_STATES:
            updated["recovery-required"] = False

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
    if not _request_lock_held:
        _finalize_worker_session_if_terminal(project_root, updated)
    return updated


def _finalize_worker_session_if_terminal(
    project_root: Path, record: dict[str, Any]
) -> None:
    """Close a request-owned worker session on *every* terminal path.

    Queue rejection/cancellation may terminalize without calling provider
    dispatch. Keeping this beside the durable request transition prevents
    those paths from leaking an active gateway session. Provider sessions are
    deliberately excluded: their runtime owns their lifetime.
    """
    if (
        record.get("provider-transport-kind") != "worker"
        or record.get("state") not in _shared.TERMINAL_STATES
        or not record.get("session-id")
    ):
        return
    try:
        from audiagentic.components.agents.gateway.session import sessions_store

        session_id = str(record["session-id"])
        session = sessions_store.read_session_record(project_root, session_id)
        if session.get("state") != "active":
            return
        if record.get("started-at"):
            sessions_store.record_session_turn(project_root, session_id, record["request-id"])
        reason = (
            "post-turn-close"
            if record.get("state") == "completed"
            else "cancelled-turn"
            if record.get("state") == "cancelled"
            else "failed"
        )
        sessions_store.transition_session_record(
            project_root,
            session_id,
            "closed",
            updates={"close-reason": reason, "closed-at": now_iso_z()},
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "failed to finalize worker-backed gateway session",
            extra={"request-id": record.get("request-id"), "session-id": record.get("session-id")},
        )


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
        updated["diagnostics"] = merge_diagnostics(
            record.get("diagnostics"),
            classify_error(
                {"code": "CON-AGW-CANCELLED"},
                phase="cancellation",
                side_effect_state=(record.get("diagnostics") or {}).get("side-effect-state")
                if isinstance(record.get("diagnostics"), dict)
                else None,
            ),
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
    diagnostics: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
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
        if expected_revision is not None and record.get("revision") != expected_revision:
            raise AudiaGenticError(
                code="CON-AGW-143",
                kind="agents",
                message="diagnostic recovery revision is stale",
                details={"request-id": request_id},
            )
        cancellation_diagnostics = merge_diagnostics(
            record.get("diagnostics"),
            diagnostics
            if isinstance(diagnostics, Mapping)
            else classify_error(
                {"code": "CON-AGW-CANCELLED"},
                phase="cancellation",
                side_effect_state=(record.get("diagnostics") or {}).get("side-effect-state")
                if isinstance(record.get("diagnostics"), dict)
                else None,
            ),
        )
        if record["state"] != "queued":
            if record["state"] == "running" and not record["cancel-requested"]:
                updated = dict(record)
                updated["cancel-requested"] = True
                updated["diagnostics"] = cancellation_diagnostics
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
            if isinstance(diagnostics, Mapping):
                updated = dict(record)
                updated["diagnostics"] = cancellation_diagnostics
                updated["updated-at"] = now_iso_z()
                updated["revision"] = record["revision"] + 1
                write_record(project_root, updated)
                return updated
            return record

        updated = dict(record)
        updated.update(
            {
                "state": "cancelled",
                "cancel-requested": True,
                "diagnostics": cancellation_diagnostics,
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


def takeover_nonterminal_owner(
    project_root: Path,
    request_id: str,
    *,
    expected_owner_epoch: str | None,
    new_owner_epoch: str,
    new_worker_id: str | None = None,
    handoff_id: str | None = None,
) -> dict[str, Any]:
    """Atomically transfer a queued/running request to a new gateway owner.

    A gateway generation is execution ownership, not request identity.  A
    restart therefore changes only the owner fence and recovery metadata; it
    never changes the request state or creates a replay request.  The old
    generation is fenced by the owner-epoch check on every later mutation.
    """
    if not new_owner_epoch:
        raise AudiaGenticError("VAL-AGW-087", "agents", "new gateway owner epoch is required", {})
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record["state"] not in {"queued", "running"}:
            return record
        current_owner = record.get("dispatch-owner-epoch")
        if expected_owner_epoch is not None and current_owner != expected_owner_epoch:
            raise AudiaGenticError(
                "CON-AGW-083", "agents", "gateway request dispatch ownership changed", {}
            )
        if current_owner == new_owner_epoch:
            return record
        previous = record.get("recovery")
        previous = previous if isinstance(previous, dict) else {}
        recovery = {
            **previous,
            "reason": "gateway-restart" if handoff_id else (previous.get("reason") or "owner-loss"),
            "outcome": "in-place",
            "from-owner-epoch": current_owner,
            "handoff-id": handoff_id or previous.get("handoff-id"),
            "attempt": int(previous.get("attempt", 0)),
        }
        updated = dict(record)
        updated.update({
            "dispatch-owner-epoch": new_owner_epoch,
            "dispatch-claimed-at": record.get("dispatch-claimed-at"),
            "updated-at": now_iso_z(),
            "recovery": recovery,
            "recovery-required": record["state"] == "running",
            "revision": record["revision"] + 1,
        })
        if new_worker_id is not None:
            updated["worker-id"] = new_worker_id
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "recovery.owner-taken-over",
            state=updated["state"],
            attributes={
                "from-owner-epoch": current_owner,
                "owner-epoch": new_owner_epoch,
                "handoff-id": handoff_id,
                "recovery-required": updated["recovery-required"],
            },
        )
        return updated


def defer_owned_recovery(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str | None,
    attempt_epoch: int,
    error: BaseException | dict[str, Any] | None,
    phase: str,
    side_effect_state: str,
    retry_delay_seconds: float | None,
    continuation: Mapping[str, Any] | None = None,
    _allow_queued: bool = False,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Persist a fenced, non-terminal recovery deferral.

    This mutation changes recovery metadata only.  It intentionally leaves
    the request running, its attempt identity, active-work index, and any
    unresolved provider checkpoint intact so a replacement gateway can adopt
    the same request and conversation.

    A None delay is explicit unscheduled node deferral, not a zero-delay timer.
    Unclaimed queued nodes require the current owner plus an exact revision;
    no fictitious worker/attempt is allocated just to describe their waiting.
    """
    unclaimed_node = _allow_queued and worker_id is None and type(attempt_epoch) is int and attempt_epoch == 0
    if unclaimed_node:
        if not owner_epoch or type(expected_revision) is not int or expected_revision < 0:
            raise AudiaGenticError("VAL-AGW-085", "agents", "Unclaimed node deferral requires owner and revision", {})
    else:
        _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    if not phase or (retry_delay_seconds is not None and retry_delay_seconds < 0):
        raise AudiaGenticError(
            "VAL-AGW-087", "agents", "recovery retry metadata is invalid", {}
        )
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if retry_delay_seconds is None and record.get("node-placement") is None:
            raise AudiaGenticError("VAL-AGW-085", "agents", "Unscheduled deferral requires node placement", {})
        if unclaimed_node and (
            record.get("node-placement") is None or record["state"] != "queued"
            or record.get("worker-id") is not None or record.get("attempt-epoch") != 0
        ):
            raise AudiaGenticError("VAL-AGW-085", "agents", "Unclaimed deferral requires a queued node request", {})
        _check_expected_identity(
            record,
            expected_revision=expected_revision,
            expected_dispatch_owner_epoch=owner_epoch,
            expected_worker_id=worker_id,
            expected_attempt_epoch=attempt_epoch,
        )
        if record["state"] != "running" and not (_allow_queued and record["state"] == "queued"):
            raise AudiaGenticError(
                "CON-AGW-088", "agents", "gateway request is not running", {}
            )
        timestamp = now_iso_z()
        previous = record.get("recovery")
        previous = previous if isinstance(previous, dict) else {}
        attempt = int(previous.get("attempt") or 0) + 1
        followup_attempt = int(previous.get("followup-attempt") or 0)
        if phase == "followup-reconcile":
            followup_attempt += 1
        retry_at = add_seconds(timestamp, retry_delay_seconds) if retry_delay_seconds is not None else None
        error_message = getattr(error, "message", None)
        if not isinstance(error_message, str) and isinstance(error, Mapping):
            error_message = error.get("message")
        if not isinstance(error_message, str):
            error_message = str(error) if error is not None else "recovery retry deferred"
        # Bounded root-error summary (code/type/kind/details): the message
        # alone cannot explain why observation-only recovery keeps deferring
        # or eventually exhausts into CON-AGW-084. The projection is flat,
        # truncated, redacted, and never carries prompt text.
        bounded_error = bounded_recovery_error(error)
        recovery = {
            "reason": previous.get("reason") or "gateway-restart",
            "outcome": "in-place",
            "from-owner-epoch": previous.get("from-owner-epoch"),
            "handoff-id": previous.get("handoff-id"),
            "attempt": attempt,
            "followup-attempt": followup_attempt,
            "last-error": error_message[:256],
            "last-error-code": bounded_error.get("code") if bounded_error else None,
            "last-error-type": bounded_error.get("type") if bounded_error else None,
            "last-error-kind": bounded_error.get("kind") if bounded_error else None,
            "last-error-details": bounded_error.get("details") if bounded_error else None,
            "phase": phase,
            "side-effect-state": side_effect_state,
            "next-retry-at": retry_at,
            "retry-delay-seconds": retry_delay_seconds if retry_delay_seconds is not None else 0,
        }
        # A provider follow-up can already have been submitted when the
        # observer loses its handle.  Preserve its bounded continuation
        # intent across the delayed retry and a gateway restart.  The
        # continuation contains only counters/flags/digests; prompt text is
        # kept in the request-owned private runtime area by the queue.
        prior_continuation = previous.get("continuation")
        if isinstance(continuation, Mapping):
            recovery["continuation"] = dict(continuation)
        elif isinstance(prior_continuation, Mapping):
            recovery["continuation"] = dict(prior_continuation)
        updated = dict(record)
        if (
            not isinstance(record.get("diagnostics"), dict)
            and side_effect_state != "not-started"
        ):
            updated["diagnostics"] = stale_progress_diagnostic(
                phase="reconciliation",
                side_effect_state=side_effect_state,
                reason_code=phase,
            )
        queued_recovery = record["state"] == "queued"
        updated.update({
            "recovery": recovery,
            "recovery-required": not queued_recovery,
            "watchdog-state": "not-started" if queued_recovery else (
                "intervention" if retry_delay_seconds is None else "active"),
            "watchdog-reason": (
                phase if retry_delay_seconds is None else (
                    "queued-recovery-retry" if queued_recovery else "recovery-retry-scheduled")
            ),
            "updated-at": timestamp,
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
    try:
        record_gateway_timeline(
            project_root, request_id,
            "recovery.deferred" if retry_delay_seconds is None else "recovery.retry-scheduled",
            state=updated["state"], attributes={
                "phase": phase, "attempt": attempt, "followup-attempt": followup_attempt,
                "next-retry-at": retry_at, "retry-delay-seconds": retry_delay_seconds,
                "side-effect-state": side_effect_state, "request-revision": updated["revision"],
                "correlation-id": updated.get("correlation-id"),
            })
    except Exception:  # noqa: BLE001 - trace failure cannot reverse committed recovery
        global _recovery_trace_failures
        with _recovery_trace_lock:
            _recovery_trace_failures += 1
            first = _recovery_trace_failures == 1
        if first:
            try:
                logger.warning("Recovery trace unavailable; canonical state retained")
            except Exception:  # noqa: BLE001 - do not recurse into a failing log sink
                pass
    return updated


def defer_owned_queued_recovery(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str | None,
    attempt_epoch: int,
    error: BaseException | dict[str, Any] | None,
    phase: str,
    side_effect_state: str,
    retry_delay_seconds: float | None,
    continuation: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Persist a recovery retry before a session turn owns the FIFO lock.

    Provider-session recovery can attach a successor or rehydrate a browser
    surface before the turn-start CAS.  If that observation path defers, the
    request is still safely queued; it must retain its claim and be retried,
    rather than being passed to the running-only recovery transition and left
    stranded with a live session.
    """
    return defer_owned_recovery(
        project_root,
        request_id,
        owner_epoch=owner_epoch,
        worker_id=worker_id,
        attempt_epoch=attempt_epoch,
        error=error,
        phase=phase,
        side_effect_state=side_effect_state,
        retry_delay_seconds=retry_delay_seconds,
        continuation=continuation,
        _allow_queued=True,
        expected_revision=expected_revision,
    )


def transition_recovered_terminal(
    project_root: Path,
    request_id: str,
    new_state: str,
    *,
    error: BaseException | dict[str, Any] | None,
    stale_epoch: str | None = None,
    expected_revision: int | None = None,
    replay_required: bool | None = None,
    replay_reason: str | None = None,
    _request_lock_held: bool = False,
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
    lock = nullcontext() if _request_lock_held else _request_lock(project_root, request_id)
    with lock:
        record = _read_record_locked(project_root, request_id)
        if expected_revision is not None and record.get("revision") != expected_revision:
            raise AudiaGenticError(
                code="CON-AGW-143",
                kind="agents",
                message="gateway request revision changed during recovery",
                details={"request-id": request_id},
            )
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
        # A running request recovered after its owning service generation
        # disappeared is an explicit gateway-restart interruption. Persist a
        # semantic diagnostic rollup so clients can distinguish this from a
        # provider failure and choose reconciliation without guessing.
        error_code = getattr(error, "code", None)
        if isinstance(error, Mapping):
            error_code = error.get("code")
        if new_state == "interrupted" and error_code == "CON-AGW-084":
            updated["diagnostics"] = merge_diagnostics(
                record.get("diagnostics"),
                classify_error(
                    error,
                    phase="reconciliation",
                    side_effect_state="may-have-started",
                ),
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
        if record.get("node-placement") is not None and record["revision"] != expected_revision:
            # Node recovery validates the complete immutable dispatch before
            # this CAS. A concurrent change must not bypass that validation
            # through the generic already-running recovery shortcut.
            raise AudiaGenticError("CON-AGW-071", "agents", "gateway request revision changed", {})
        if (
            record["state"] == "running"
            and record.get("recovery-required") is True
            and record.get("dispatch-owner-epoch") == owner_epoch
        ):
            # Recovery workers inherit an already-running request. Returning a
            # private marker lets the queue skip the queued-to-running CAS;
            # the durable request remains running throughout takeover.
            record_active_work(service_root, project_root, request_id, owner_epoch=owner_epoch)
            return {**record, "_recovered-dispatch": True}
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
        # Already owned by this epoch: a no-op only when the service root is
        # recorded too. Restart takeover transfers the owner of an admitted,
        # never-claimed request without one; node receipt and publication
        # custody require it, so complete the claim instead of returning.
        if current_owner == owner_epoch and (
            service_root is None or record.get("dispatch-service-root")
        ):
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


def prepare_owned_session_attempt(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    expected_revision: int,
    resolved_source_id: str | None = None,
    resolved_model_id: str | None = None,
    resolved_model_selector: str | None = None,
    resolved_capacity_generation: str | None = None,
) -> dict[str, Any]:
    """Assign an owned session attempt without claiming RUNNING yet.

    Queue admission/claim may launch a session worker before that worker owns
    the session's turn lock. This durable preparation records the worker and
    attempt fence while preserving QUEUED; ``start_owned_session_attempt`` is
    the only transition to RUNNING and is called under that turn lock.
    """
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
        if record["state"] != "queued":
            raise AudiaGenticError(
                "CON-AGW-087", "agents", "gateway session request is no longer queued", {}
            )
        if record.get("cancel-requested"):
            raise AudiaGenticError(
                "CON-AGW-CANCELLED", "agents", "gateway session request was cancelled", {}
            )
        timestamp = now_iso_z()
        updated = dict(record)
        updated.update(
            {
                "worker-id": worker_id,
                "attempt-epoch": record["attempt-epoch"] + 1,
                "updated-at": timestamp,
                "revision": record["revision"] + 1,
            }
        )
        if resolved_source_id is not None:
            updated["resolved-source-id"] = resolved_source_id
        if resolved_model_id is not None:
            updated["resolved-model-id"] = resolved_model_id
        if resolved_model_selector is not None:
            updated["resolved-model-selector"] = resolved_model_selector
        if resolved_capacity_generation is not None:
            updated["resolved-capacity-generation"] = resolved_capacity_generation
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "session-attempt.prepared",
            state="queued",
            attributes={
                "dispatch-owner-epoch": owner_epoch,
                "worker-id": worker_id,
                "attempt-epoch": updated["attempt-epoch"],
            },
        )
        return updated


def start_owned_session_attempt(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
) -> dict[str, Any]:
    """Atomically claim RUNNING after the session turn lock is owned."""
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
        if record["state"] == "running":
            return record
        if record["state"] != "queued":
            raise AudiaGenticError(
                "CON-AGW-087", "agents", "gateway session request is not dispatchable", {}
            )
        if record.get("cancel-requested"):
            raise AudiaGenticError(
                "CON-AGW-CANCELLED", "agents", "gateway session request was cancelled", {}
            )
        timestamp = now_iso_z()
        updated = dict(record)
        updated.update(
            {
                "state": "running",
                "started-at": timestamp,
                "updated-at": timestamp,
                "watchdog-state": "active",
                "watchdog-reason": "awaiting-verified-activity",
                "revision": record["revision"] + 1,
            }
        )
        write_record(project_root, updated)
        service_root = (
            Path(record["dispatch-service-root"])
            if isinstance(record.get("dispatch-service-root"), str)
            and record.get("dispatch-service-root")
            else None
        )
        if service_root is not None:
            try:
                update_work_index_phase(
                    service_root,
                    request_id,
                    from_phase="claimed",
                    to_phase="running",
                    owner_epoch=owner_epoch,
                )
            except OSError:
                logger.warning(
                    "work-index phase update failed at session turn start (non-fatal)",
                    extra={"request-id": request_id},
                )
        record_gateway_timeline(
            project_root,
            request_id,
            "session-attempt.started",
            state="running",
            attributes={
                "dispatch-owner-epoch": owner_epoch,
                "worker-id": worker_id,
                "attempt-epoch": attempt_epoch,
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
    normalized_source = activity_source.strip().lower().replace("_", "-").replace(" ", "-")
    return record_owned_activity(
        project_root,
        request_id,
        owner_epoch=owner_epoch,
        worker_id=worker_id,
        attempt_epoch=attempt_epoch,
        kind=(
            "client-liveness"
            if normalized_source in {"soft-liveness", "delivery-timeout-retry"}
            else "provider"
            if is_meaningful_activity(activity_source, activity_source)
            else "owner-heartbeat"
        ),
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
    if kind not in {"provider", "owner-heartbeat", "client-liveness"}:
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
        if kind == "owner-heartbeat":
            # Ownership/process heartbeats are useful audit evidence, but are
            # not provider work and therefore cannot renew the meaningful
            # activity lease or clear a stale-progress observation.
            activity["owner"] = bucket
            updated = dict(record)
            updated["activity"] = activity
            updated["updated-at"] = received_at
            updated["revision"] = record["revision"] + 1
            write_record(project_root, updated)
            record_gateway_timeline(
                project_root,
                request_id,
                "activity.owner-heartbeat",
                state="running",
                attributes={"activity-source": source, "activity-kind": kind},
            )
            return updated
        if kind == "client-liveness":
            # Advance the public activity count without touching the provider
            # bucket or its watchdog lease. Synthetic activity must not mask a
            # stalled provider turn.
            activity["owner"] = bucket
            activity.update({"sequence": aggregate, "last-at": received_at, "last-source": source})
            updated = dict(record)
            updated.update(
                {
                    "last-activity-at": received_at,
                    "activity-sequence": aggregate,
                    "activity-source": source,
                    "activity": activity,
                    "updated-at": received_at,
                    "revision": record["revision"] + 1,
                }
            )
            write_record(project_root, updated)
            record_gateway_timeline(
                project_root,
                request_id,
                "activity.client-liveness",
                state="running",
                attributes={
                    "activity-sequence": aggregate,
                    "activity-source": source,
                    "activity-kind": kind,
                    "activity-label": normalize_activity_label(phase) or phase,
                },
            )
            return updated
        normalized_label: str | None = None
        if kind == "provider":
            bucket["first-at"] = bucket.get("first-at") or received_at
            normalized_label = normalize_activity_label(phase)
            bucket["phase"] = normalized_label or phase
            bucket["activity-label"] = normalized_label
            bucket["activity-group"] = activity_group(normalized_label)
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
            if diagnostics.get("classification") == "stale-progress":
                diagnostics.update({
                    "resolution-state": "resolved",
                    "reason-code": "activity-resumed",
                    "recovery": {"disposition": "none", "allowed-actions": []},
                })
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
            attributes={
                "activity-sequence": aggregate,
                "activity-source": source,
                "activity-kind": kind,
                **(
                    {
                        "activity-label": normalized_label,
                        "activity-group": activity_group(normalized_label),
                    }
                    if kind in {"provider", "client-liveness"} and normalized_label
                    else {}
                ),
            },
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
    from datetime import datetime, timedelta, timezone

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
        # Before the first accepted provider activity there is no activity
        # lease to expire. Use the admission-frozen initial grace instead so a
        # watcher that has lost its DOM observation path gets one diagnostic
        # reconciliation opportunity rather than remaining at sequence zero
        # forever. This is non-terminal and never proves provider failure.
        provider_phase = provider.get("phase")
        provider_activity_is_real = (
            (provider_phase is None and not provider.get("source"))
            or is_meaningful_activity(provider.get("source"), provider_phase)
        )
        first_activity = (
            provider.get("first-at") or provider.get("last-at")
        ) if provider_activity_is_real else None
        policy = record.get("watchdog-policy")
        initial_grace = 30.0
        if isinstance(policy, dict):
            try:
                candidate = float(policy.get("initial-activity-grace-seconds", 30.0))
                if candidate > 0:
                    initial_grace = candidate
            except (TypeError, ValueError):
                pass
        initial_observation_expired = False
        if not first_activity:
            started = record.get("started-at")
            try:
                started_at = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                initial_observation_expired = datetime.now(timezone.utc) >= started_at + timedelta(seconds=initial_grace)
            except (TypeError, ValueError):
                initial_observation_expired = False
        if (
            record.get("provider-transport-kind") == "provider-session"
            and not first_activity
            and not initial_observation_expired
        ):
            # There is no provider lease before the initial observation grace
            # elapses. Do not treat that intentional gap as an expired lease.
            return record
        if initial_observation_expired:
            expiry = None
        elif record.get("provider-transport-kind") == "provider-session":
            # Provider-session watchdog decisions must use provider-owned
            # activity only; aggregate liveness may be synthetic.
            expiry = (
                provider.get("lease-expires-at")
                if (
                    provider_activity_is_real
                    and provider.get("capability") == "supported"
                    and provider.get("last-at")
                )
                else None
            )
        else:
            expiry = (
                provider.get("lease-expires-at")
                if (
                    provider_activity_is_real
                    and provider.get("capability") == "supported"
                    and provider.get("last-at")
                )
                else record.get("activity-lease-expires-at")
            )
        reason_code = (
            "initial-activity-observation-expired"
            if initial_observation_expired
            else "activity-lease-expired"
        )
        evidence_kind = (
            "initial-activity-timeout"
            if initial_observation_expired
            else "activity-lease-expired"
        )
        watchdog_reason = (
            "initial-activity-observation-expired"
            if initial_observation_expired
            else "activity-lease-expired-diagnostic"
        )
        if provider.get("capability") == "unsupported" and not initial_observation_expired:
            return record
        if initial_observation_expired:
            expired = True
        elif not isinstance(expiry, str) or not expiry.strip():
            # Missing/corrupt persisted leases must not keep work alive.
            expired = True
        else:
            try:
                parsed_expiry = datetime.fromisoformat(
                    expiry.replace("Z", "+00:00")
                )
                if parsed_expiry.tzinfo is None:
                    parsed_expiry = parsed_expiry.replace(tzinfo=timezone.utc)
                expired = parsed_expiry <= datetime.now(timezone.utc)
            except (TypeError, ValueError, OverflowError, AttributeError):
                # A malformed lease is diagnostic evidence, not liveness.
                expired = True
        if not expired or record.get("watchdog-state") == "intervention":
            return record
        timestamp = now_iso_z()
        updated = dict(record)
        diagnostics = stale_progress_diagnostic(reason_code=reason_code)
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
                "kind": evidence_kind,
                "certainty": "weak",
                "side-effect-state": "may-have-started",
                "source": "gateway-watchdog",
                "source-sequence": None,
            }]
        )[-8:]
        updated.update({
            "watchdog-state": "intervention",
            "watchdog-reason": watchdog_reason,
            "updated-at": timestamp,
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "activity.lease-expired-diagnostic",
            state="running",
            attributes={"attempt-epoch": attempt_epoch, "reason-code": reason_code},
        )
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
    warnings: list[dict[str, Any]] | None = None,
    recovery_chat_url: str | None = None,
    result_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach the live session id to the current owned session attempt.

    Keep-alive requests may open their provider session while the request is
    still queued behind the session turn lock. Runtime diagnostics need that
    session id immediately, while the terminal result write remains
    responsible for final output/completion fields. The owner/worker/attempt
    fence prevents a stale pre-lock worker from mutating a successor.
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
        if record["state"] not in {"queued", "running"}:
            raise AudiaGenticError(
                "CON-AGW-087",
                "agents",
                "gateway request is not an active session attempt",
                {"request-id": request_id, "state": record["state"]},
            )
        current_metadata = record.get("provider-metadata")
        current_metadata = current_metadata if isinstance(current_metadata, dict) else {}
        metadata_unchanged = provider_metadata is None or dict(provider_metadata) == current_metadata
        current_warnings = record.get("warnings")
        current_warnings = current_warnings if isinstance(current_warnings, list) else []
        warnings_unchanged = warnings is None or list(warnings)[-3:] == current_warnings
        current_request_metadata = record.get("metadata")
        current_request_metadata = current_request_metadata if isinstance(current_request_metadata, dict) else {}
        recovery_url_unchanged = (
            recovery_chat_url is None
            or current_request_metadata.get("provider-chat-url") == recovery_chat_url
        )
        updates_unchanged = not result_updates or all(
            record.get(key) == value for key, value in result_updates.items()
        )
        if (
            record.get("session-id") == session_id
            and metadata_unchanged
            and warnings_unchanged
            and recovery_url_unchanged
            and updates_unchanged
        ):
            return record
        updated = dict(record)
        updated["session-id"] = session_id
        if warnings is not None or recovery_chat_url:
            if warnings is not None:
                updated["warnings"] = list(warnings)[-3:]
            metadata = dict(updated.get("metadata") or {})
            metadata.pop("provider-chat-url", None)
            if recovery_chat_url:
                metadata["provider-chat-url"] = recovery_chat_url
            updated["metadata"] = metadata
        if provider_metadata is not None:
            updated["provider-metadata"] = dict(provider_metadata)
        if result_updates:
            for key, value in result_updates.items():
                if key not in _shared._MUTABLE_RESULT_FIELDS:
                    raise AudiaGenticError(
                        "VAL-AGW-088", "agents", "invalid running result update", {"field": key}
                    )
                updated[key] = value
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
    expected_revision: int | None = None,
    service_root: Path | None = None,
    _request_lock_held: bool = False,
) -> dict[str, Any]:
    """Write a terminal result only with dispatch and optional revision fences.

    The private lock-held mode reuses the canonical transition implementation;
    its coordinator owns subsequent session finalization outside the lock.
    """
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
    terminal_updates["recovery-required"] = False
    updated = transition_record(
        project_root,
        request_id,
        new_state,
        updates=terminal_updates,
        expected_revision=expected_revision,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id,
        expected_attempt_epoch=attempt_epoch,
        _request_lock_held=_request_lock_held,
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


def transition_operator_terminal(
    project_root: Path,
    request_id: str,
    *,
    expected_revision: int,
    updates: dict[str, Any],
    recovery_attempt_id: str | None = None,
    recovery_claim_generation: int | None = None,
    session_id: str | None = None,
    expected_session_provider: dict[str, Any] | None = None,
    expected_session_binding: dict[str, Any] | None = None,
    recovered_binding: dict[str, Any] | None = None,
    clear_unresolved_turn: bool = False,
) -> dict[str, Any]:
    """Terminalize a request from an operator after a compare-and-swap.

    Clearing the dispatch fence is intentional: a provider worker may still be
    unwinding after the operator captured the already-rendered answer, and its
    later terminal write must be rejected rather than overwrite this result.
    """
    def assert_current_capture_claim() -> None:
        # Call only while _request_lock is held. replay's claim preparation,
        # renewal and result writers use this same request mutation.lock, so
        # journal identity cannot change between this check and write_record.
        if recovery_attempt_id is not None:
            from audiagentic.components.agents.agents_paths import gateway_recovery_action_path
            from audiagentic.components.agents.gateway.replay import (
                RecoveryClaimLostError,
                recovery_claim_state,
            )
            from audiagentic.foundation.io import iter_ndjson

            claim = recovery_claim_state(
                iter_ndjson(gateway_recovery_action_path(project_root, request_id))
            )
            if not (
                claim
                and claim.get("valid")
                and claim.get("active") is True
                and claim.get("result") is None
                and claim.get("action-attempt-id") == recovery_attempt_id
                and claim.get("claim-generation") == recovery_claim_generation
            ):
                raise RecoveryClaimLostError("recovery claim lost before terminal commit")
    with _request_lock(project_root, request_id):
        assert_current_capture_claim()
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=expected_revision,
            expected_dispatch_owner_epoch=None,
            expected_worker_id=None,
            expected_attempt_epoch=None,
        )
        if record["state"] == "completed":
            return record
        if record["state"] not in {
            "queued",
            "running",
            "interrupted",
            "failed",
            "cancelled",
            "timed-out",
            "expired",
            "abandoned",
        }:
            raise AudiaGenticError(code="CON-AGW-151", kind="agents", message="request is not operator-completable", details={})
        updated = dict(record)
        # Older v8 records may carry the transitional preview fields even
        # though the canonical artifact schema no longer persists them.
        # Rebuild the preview from response-artifact on read instead of
        # allowing an operator terminalization to preserve stale fields.
        updated.pop("output-preview", None)
        updated.pop("output-truncated", None)
        updated.update({"state": "completed", "updated-at": now_iso_z(), "finished-at": now_iso_z()})
        updated["revision"] = record["revision"] + 1
        updated.update({"worker-id": None, "dispatch-owner-epoch": None, "dispatch-claimed-at": None})
        updated["watchdog-state"] = "not-started"
        updated["watchdog-reason"] = None
        updated["recovery-required"] = False
        diagnostics = updated.get("diagnostics")
        if isinstance(diagnostics, dict):
            updated["diagnostics"] = {
                **diagnostics, "resolution-state": "resolved",
                "recovery": {"disposition": "none", "allowed-actions": []},
            }
        finalization = None
        if session_id and (recovered_binding or clear_unresolved_turn):
            finalization = {
                "session-id": session_id,
                "recovered-binding": dict(recovered_binding or {}),
                "clear-unresolved-turn": bool(clear_unresolved_turn),
            }
            checkpoint = (expected_session_provider or {}).get("metadata")
            if (
                isinstance(checkpoint, dict)
                and checkpoint.get("unresolved-turn-id") == request_id
                and checkpoint.get("unresolved-turn-pending") is True
            ):
                from audiagentic.components.agents.gateway.session.sessions_store import (
                    _RECOVERY_CHECKPOINT_KEYS,
                )
                finalization["pre-clear-checkpoint"] = {
                    key: value for key, value in checkpoint.items()
                    if key in _RECOVERY_CHECKPOINT_KEYS
                }
                finalization["expected-session-binding"] = expected_session_binding
                finalization["capture-owner"] = {
                    key: record.get(key)
                    for key in ("dispatch-owner-epoch", "worker-id", "attempt-epoch")
                }
            updated["terminal-finalization"] = finalization
        updates = dict(updates)
        final_response_text = updates.pop("__final-response-text", None)
        if final_response_text is not None:
            from audiagentic.components.agents.gateway.output import persist_final_response

            artifact = persist_final_response(
                project_root,
                request_id,
                str(final_response_text),
                lock_held=True,
                allow_terminal=True,
            )
            updates["response-artifact"] = {
                key: artifact[key]
                for key in ("artifact-id", "request-id", "media-type", "bytes", "sha256")
            }
        for key, value in updates.items():
            updated[key.replace("_", "-")] = value
        if session_id and expected_session_provider is not None:
            from audiagentic.components.agents.gateway.session import sessions_store

            # A successor turn can change only the session checkpoint while
            # this request's revision stays unchanged. Recheck that checkpoint
            # under the session lock and hold it through the terminal write.
            with sessions_store._ordered_session_mutation_lock(project_root, session_id):
                current_session = sessions_store.read_session_record(project_root, session_id)
                if (
                    current_session.get("provider") != expected_session_provider
                    or current_session.get("binding") != expected_session_binding
                ):
                    raise AudiaGenticError(
                        code="CON-AGW-156", kind="agents",
                        message="provider session changed during response capture",
                        details={"request-id": request_id},
                    )
                # Session/retention lock acquisition and artifact persistence
                # can outlive the lease checked at entry. Revision/CAS alone
                # cannot prove this recovery attempt is still authorized.
                assert_current_capture_claim()
                write_record(project_root, updated)
        else:
            assert_current_capture_claim()
            write_record(project_root, updated)
        record_gateway_timeline(
            project_root, request_id, "state.changed", state="completed",
            attributes={"from": record["state"], "to": "completed", "source": "operator-provider-capture"},
        )
        if finalization is not None:
            try:
                applied = _apply_terminal_finalization(project_root, request_id, finalization)
            except Exception:  # noqa: BLE001 - marker remains replayable
                logger.warning(
                    "terminal session finalization deferred",
                    extra={"request-id": request_id},
                    exc_info=True,
                )
            else:
                if applied and "pre-clear-checkpoint" not in finalization:
                    updated = _read_record_locked(project_root, request_id)
                    updated.pop("terminal-finalization", None)
                    updated["updated-at"] = now_iso_z()
                    updated["revision"] = record["revision"] + 2
                    write_record(project_root, updated)
    _finalize_worker_session_if_terminal(project_root, updated)
    if finalization is not None and "pre-clear-checkpoint" in finalization:
        from ..session.capture_handoff import reconcile_idle_captured_handoff
        try:
            if reconcile_idle_captured_handoff(project_root, request_id):
                updated = _read_record_locked(project_root, request_id)
        except Exception:  # noqa: BLE001 - durable marker remains for the owner/status replay
            logger.warning("captured memory handoff deferred", exc_info=True)
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
    resolved_model_selector: str | None = None,
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
                "resolved-model-selector": resolved_model_selector,
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
                "resolved-model-selector": resolved_model_selector,
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


# Node dispatch writes are local CAS operations, never channel/grant authority.
# The caller serializes them with current service authorization/revocation.
def _node_identity(value: Any) -> dict[str, Any]:
    from audiagentic.components.agents.gateway.node.contracts import CommandIdentity

    return (value if isinstance(value, CommandIdentity)
            else CommandIdentity.from_mapping(value)).to_mapping()


def _node_conflict(message: str) -> AudiaGenticError:
    from audiagentic.components.agents.gateway.node.contracts import conflict

    return conflict(1, message)


def _node_owned_record(
    project_root: Path, request_id: str, *, owner_epoch: str, worker_id: str,
    attempt_epoch: int, expected_revision: int,
) -> dict[str, Any]:
    if (
        not owner_epoch or not worker_id or type(attempt_epoch) is not int
        or attempt_epoch < 1 or type(expected_revision) is not int or expected_revision < 0
    ):
        raise _node_conflict("Node mutation requires complete owned attempt fences")
    record = _read_record_locked(project_root, request_id)
    _check_expected_identity(
        record, expected_revision=expected_revision,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id, expected_attempt_epoch=attempt_epoch,
    )
    return record


def _node_matches_record(record: dict[str, Any], identity: dict[str, Any]) -> None:
    if (
        identity["request-id"] != record["request-id"]
        or identity["execution-profile-id"] != record["execution-profile-id"]
    ):
        raise _node_conflict("Node command does not match the admitted request")
    # _read_record_locked has already validated the complete strict placement
    # tuple. Null is valid for ordinary server admission, never for node work.
    # Principal/project facts stay sealed here for the outer grant owner;
    # this local consistency guard does not recreate grant authorization.
    placement = record.get("node-placement")
    if not isinstance(placement, dict):
        raise _node_conflict("Node command requires sealed admission placement")
    if any(
        identity[key] != placement[key] for key in ("node-id", "workspace-id", "grant-revision")
    ):
        raise _node_conflict("Node command does not match immutable admission placement")


def _node_attestation_matches_attempt(record: dict[str, Any], attestation: Any) -> None:
    # These are canonical execution-owner facts. Provider/model identity is
    # node-local preparation evidence and must not be inferred from unrelated
    # or not-yet-populated central provider/model fields.
    if (
        attestation.worker_id != record["worker-id"]
        or type(attestation.attempt_epoch) is not int
        or attestation.attempt_epoch != record["attempt-epoch"]
    ):
        raise _node_conflict("Accepted node attestation does not match the owned worker attempt")


def _node_fresh_effect(record: dict[str, Any], identity: dict[str, Any], owner_epoch: str) -> None:
    _node_matches_record(record, identity)
    if (
        record["state"] != "running" or record.get("cancel-requested")
        or record.get("recovery-required")
        or identity["gateway-owner-epoch"] != owner_epoch
    ):
        raise _node_conflict("Node command is not eligible for fresh effect authorization")


def _write_node_dispatch(project_root: Path, record: dict[str, Any], dispatch: dict[str, Any], *,
                         clear_recovery: bool = False) -> dict[str, Any]:
    updated = dict(record)
    updated.update({
        "node-dispatch": dispatch, "revision": record["revision"] + 1,
        "updated-at": now_iso_z(),
    })
    if clear_recovery:
        updated.update({"recovery-required": False, "watchdog-state": "active",
                        "watchdog-reason": "node-recovery-bound"})
    write_record(project_root, updated)
    return updated


def bind_owned_node_dispatch(
    project_root: Path, request_id: str, *, identity: Any,
    command_payload: Mapping[str, Any], accepted_attestation: Any,
    owner_epoch: str, worker_id: str, attempt_epoch: int, expected_revision: int,
    resume_unbound: bool = False,
) -> dict[str, Any]:
    """Persist one immutable attested command identity; return the full record.

    This is not a grant check or permission to invoke a native effect. A
    different identity always conflicts, including after an owner reconnect.
    Rebinding an existing command is prohibited. An explicitly recovered null
    dispatch may install its first newly attested binding and clear recovery in
    one write, under the caller's current service/grant/occupancy fences.
    command_payload is the protected final semantic/raw-prompt/attestation
    mapping; only its validated identity and accepted attestation digest persist.
    Supply accepted_attestation from the trusted preparation exchange, never
    copied from the command. Unknown legacy attestations cannot be rebound.
    """
    from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
    from audiagentic.components.agents.gateway.node.preparation import (
        validate_final_command_payload,
    )

    if type(resume_unbound) is not bool:
        raise _node_conflict("Node recovered binding flag must be boolean")
    command = _node_identity(identity)
    attestation = validate_final_command_payload(
        command_payload, CommandIdentity.from_mapping(command),
        accepted_attestation=accepted_attestation,
    )
    attestation_digest = attestation.digest
    with _request_lock(project_root, request_id):
        record = _node_owned_record(
            project_root, request_id, owner_epoch=owner_epoch, worker_id=worker_id,
            attempt_epoch=attempt_epoch, expected_revision=expected_revision,
        )
        _node_attestation_matches_attempt(record, accepted_attestation)
        prior = record.get("node-dispatch")
        if resume_unbound:
            _node_matches_record(record, command)
            if (prior is not None or record["state"] != "running"
                    or record.get("recovery-required") is not True
                    or record.get("cancel-requested") or command["gateway-owner-epoch"] != owner_epoch):
                raise _node_conflict("Recovered node binding requires an owned unsent attempt")
        else:
            _node_fresh_effect(record, command, owner_epoch)
        if prior is not None:
            if prior["identity"] != command or prior.get("attestation-sha256") != attestation_digest:
                raise _node_conflict("Node dispatch identity collision")
            return record
        return _write_node_dispatch(project_root, record, {
            "identity": command, "attestation-sha256": attestation_digest, "authorization-id": None,
            "authorization-state": "not-authorized",
            "receipt-sequence": 0, "receipt-sha256": None,
            "receipt-stage": None, "output-sha256": None,
        }, clear_recovery=resume_unbound)


def authorize_owned_node_effect(
    project_root: Path, request_id: str, *, identity: Any, authorization_id: str,
    accepted_attestation: Any,
    current_node_epoch: str, current_connection_generation: int,
    owner_epoch: str, worker_id: str, attempt_epoch: int, expected_revision: int,
) -> dict[str, Any]:
    """Durably record caller-validated live authorization; return full record.

    Invoke under the outer service auth lock with the currently validated
    epoch/generation. Idempotent replay is only a persisted authorization
    result, never permission for another native call. Uncertain/observed/
    terminal commands cannot receive fresh authorization here.
    """
    from audiagentic.components.agents.gateway.node.contracts import _identifier
    from audiagentic.components.agents.gateway.node.preparation import PreparationAttestation

    if type(accepted_attestation) is not PreparationAttestation:
        raise _node_conflict("Node authorization requires a typed accepted preparation attestation")
    attestation_digest = accepted_attestation.digest
    command = _node_identity(identity)
    _identifier(authorization_id)
    if (
        type(current_connection_generation) is not int
        or command["connection-generation"] != current_connection_generation
        or command["node-epoch"] != current_node_epoch
    ):
        raise _node_conflict("Cannot authorize a stale node connection")
    with _request_lock(project_root, request_id):
        record = _node_owned_record(
            project_root, request_id, owner_epoch=owner_epoch, worker_id=worker_id,
            attempt_epoch=attempt_epoch, expected_revision=expected_revision,
        )
        _node_attestation_matches_attempt(record, accepted_attestation)
        _node_fresh_effect(record, command, owner_epoch)
        prior = record.get("node-dispatch")
        if prior is None or prior["identity"] != command:
            raise _node_conflict("Node authorization identity collision")
        if prior.get("attestation-sha256") is None or prior["attestation-sha256"] != attestation_digest:
            raise _node_conflict("Node authorization does not match the bound accepted attestation")
        if prior["authorization-state"] == "authorized":
            if prior["authorization-id"] != authorization_id:
                raise _node_conflict("Node authorization identity changed")
            return record
        if prior["authorization-state"] != "not-authorized" or prior["authorization-id"] is not None:
            raise _node_conflict("Prior node effect requires evidence reconciliation")
        return _write_node_dispatch(project_root, record, {
            **prior, "authorization-id": authorization_id, "authorization-state": "authorized",
        })


def fence_node_dispatch_no_effect(
    project_root: Path, request_id: str, *, identity: Any,
    owner_epoch: str, worker_id: str, attempt_epoch: int, expected_revision: int,
    retired_connection_generation: int,
) -> dict[str, Any]:
    """Durably prove the original binding never obtained authorization.

    Caller must supply retired_connection_generation from the owning
    connection authority's own serialized generation counter for this exact
    node, strictly greater than the original bound connection-generation. A
    send timeout, reconnect gap or peer absence alone is never sufficient:
    only a newer connection the owner itself admitted proves the original one
    is gone, since at most one connection per node is ever live at a time.
    This never resends, rebinds or clears the original identity, attestation,
    worker or attempt; it only fences this exact binding against any later
    authorization and marks it as positively having no effect.

    The generation counter is scoped to one connection-owner-authority
    instance (one per live gateway owner epoch) and resets across a
    restart. A caller's generation proof is therefore only meaningful
    against a binding made under that SAME owner epoch; comparing it
    against a binding from a prior, retired owner epoch would compare two
    unrelated counters and can produce a false positive. owner_epoch here
    is the live caller fence (checked by _node_owned_record below); this
    additionally requires the historical binding's own recorded epoch to
    equal it, never extending proof across an owner takeover.
    """
    command = _node_identity(identity)
    if (
        type(retired_connection_generation) is not int
        or retired_connection_generation <= command["connection-generation"]
    ):
        raise _node_conflict("No-effect fence requires a proven strictly newer connection generation")
    with _request_lock(project_root, request_id):
        record = _node_owned_record(
            project_root, request_id, owner_epoch=owner_epoch, worker_id=worker_id,
            attempt_epoch=attempt_epoch, expected_revision=expected_revision,
        )
        # owner_epoch is now confirmed to be the current live record owner.
        # The generation proof is only meaningful against a binding made
        # under that SAME epoch's connection-owner-authority instance.
        if command["gateway-owner-epoch"] != owner_epoch:
            raise _node_conflict("No-effect fence requires a proven strictly newer connection generation")
        _node_matches_record(record, command)
        prior = record.get("node-dispatch")
        if (
            prior is None or prior["identity"] != command
            or prior["authorization-state"] != "not-authorized"
            or prior["authorization-id"] is not None
        ):
            raise _node_conflict("No-effect fence requires an original unauthorized binding")
        return _write_node_dispatch(project_root, record, {
            **prior, "authorization-state": "no-effect",
        })


def apply_owned_node_receipt(
    project_root: Path, request_id: str, *, receipt: Mapping[str, Any],
    owner_epoch: str, worker_id: str, attempt_epoch: int, expected_revision: int,
) -> dict[str, Any]:
    """Checkpoint a public Receipt.public_payload mapping; return full record.

    Exact latest replay does not write. Older sequences and changed replays
    conflict. Gaps are valid: the receipt outbox sequence is node-wide, not
    command-local. A later stage may therefore also arrive as a snapshot.
    Historical node epochs are evidence for the ORIGINAL bound command only;
    this never rebinds or authorizes effects or changes request lifecycle.
    """
    import hashlib
    import re

    from audiagentic.components.agents.gateway.node.contracts import canonical_json

    if not isinstance(receipt, Mapping) or set(receipt) != {
        "identity", "state", "receipt-sequence", "output-sha256",
    }:
        raise _node_conflict("Invalid public node receipt fields")
    command = _node_identity(receipt["identity"])
    sequence = receipt["receipt-sequence"]
    stage = receipt["state"]
    stages = {"prepared": 0, "effect-intent": 1, "native-accepted": 2, "terminal": 3}
    output = receipt["output-sha256"]
    if (
        type(sequence) is not int or not 1 <= sequence <= 2**63 - 1
        or not isinstance(stage, str) or stage not in stages
        or (stage == "terminal" and (not isinstance(output, str) or re.fullmatch(r"[0-9a-f]{64}", output) is None))
        or (stage != "terminal" and output is not None)
    ):
        raise _node_conflict("Invalid node receipt sequence, stage or output digest")
    # Freeze caller-owned input before locking; persist no native ref/text.
    receipt_digest = hashlib.sha256(canonical_json({
        "identity": command, "state": stage, "receipt-sequence": sequence, "output-sha256": output,
    })).hexdigest()
    with _request_lock(project_root, request_id):
        record = _node_owned_record(
            project_root, request_id, owner_epoch=owner_epoch, worker_id=worker_id,
            attempt_epoch=attempt_epoch, expected_revision=expected_revision,
        )
        _node_matches_record(record, command)
        prior = record.get("node-dispatch")
        if prior is None or prior["identity"] != command:
            raise _node_conflict("Node receipt identity collision")
        if sequence == prior["receipt-sequence"]:
            if receipt_digest != prior["receipt-sha256"]:
                raise _node_conflict("Node receipt replay changed")
            return record
        if sequence < prior["receipt-sequence"]:
            raise _node_conflict("Node receipt sequence regressed")
        previous_stage = prior["receipt-stage"]
        if previous_stage is not None and (
            stages[stage] < stages[previous_stage] or previous_stage == "terminal"
        ):
            raise _node_conflict("Node receipt stage regressed or terminal evidence changed")
        if stage != "prepared" and prior["authorization-id"] is None:
            raise _node_conflict("Node effect receipt has no durable authorization")
        state = {
            "effect-intent": "uncertain", "native-accepted": "effect-observed", "terminal": "terminal",
        }.get(stage, prior["authorization-state"])
        return _write_node_dispatch(project_root, record, {
            **prior, "authorization-state": state, "receipt-sequence": sequence,
            "receipt-sha256": receipt_digest, "receipt-stage": stage, "output-sha256": output,
        })
