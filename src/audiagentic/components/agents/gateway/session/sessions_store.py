"""Agent Execution Gateway session record store (plan agent-sessions AS03/AS30).

Durable, observable state for live agent sessions. Live transport handles are
in-memory only (agents_gateway_sessions.SessionRuntime); these records are the
audit trail and protected provider binding anchor for later build-out
(AS10 resume, AS09 remote channeling). Follows agents_gateway_store conventions
exactly: atomic JSON records, schema validation, workflow-driven transitions,
NDJSON timeline, per-record locks.

No prompt or output content is ever persisted here — content lives on request
records, which carry the redaction discipline (Standard 8). Session records
hold lifecycle metadata only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_retention_lock_path,
    gateway_session_generation_lock_path,
    gateway_session_path,
    gateway_session_timeline_path,
    gateway_sessions_root,
)
from audiagentic.components.agents.gateway.session import bindings as bindings
from audiagentic.components.agents.gateway.store._shared import _request_lock
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json, iter_ndjson
from audiagentic.foundation.observability import record_timeline_event
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    states_in_set,
    transition_allowed,
)

logger = logging.getLogger(__name__)

_SCHEMA_STEM = "agent-execution-session"
_WORKFLOW = load_workflow(Path(__file__).parent.parent.parent / "workflows.yaml", "gateway-session")
SESSION_TERMINAL_STATES: set[str] = set(states_in_set(_WORKFLOW, "terminal"))


def session_state_is_reusable(state: object) -> bool:
    """Return whether a durable session may admit another provider turn."""
    return isinstance(state, str) and is_known_state(_WORKFLOW, state) and state == "active"

_REDACTED_ERROR_KEYS = {"code", "message", "kind"}

# Lifecycle fields a workflow transition may update. Everything else on the
# record is identity, immutable after creation (AS30 generation model).
_MUTABLE_TRANSITION_FIELDS = {"close-reason", "closed-at", "last-activity-at", "error"}

_COMPONENT_ID = "agents"
_RESOURCE_KIND = "agent-execution-gateway-session"


def _terminal_checkpoint_fingerprint(
    metadata: dict[str, Any], *, turn_id: str
) -> str | None:
    """Hash immutable prompt/baseline identity without exposing provider IDs."""
    if (
        not isinstance(turn_id, str)
        or not turn_id
        or not isinstance(metadata.get("submission-attempt-id"), str)
        or not metadata.get("submission-attempt-id")
        or not isinstance(metadata.get("prompt-text-digest"), str)
        or not metadata.get("prompt-text-digest")
        or isinstance(metadata.get("unresolved-baseline-user-count"), bool)
        or not isinstance(metadata.get("unresolved-baseline-user-count"), int)
        or isinstance(metadata.get("unresolved-baseline-assistant-count"), bool)
        or not isinstance(metadata.get("unresolved-baseline-assistant-count"), int)
        or not isinstance(
            metadata.get("unresolved-baseline-error-alert-occurrences"), list
        )
    ):
        return None
    identity = {
        "turn-id": turn_id,
        "fields": {
            key: {"present": key in metadata, "value": metadata.get(key)}
            for key in _TERMINAL_CHECKPOINT_IDENTITY_KEYS
        },
    }
    try:
        encoded = json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


_RECOVERY_CHECKPOINT_KEYS = frozenset(
    {
        "unresolved-turn-pending",
        "unresolved-turn-id",
        "submission-state",
        "submission-attempt-id",
        "submission-stage",
        "send-intent-ever",
        "submission-proven",
        "submission-proof-source",
        "submission-recovery-claim",
        "submission-recovery-generation",
        "recovery-state",
        "prompt-text-digest",
        "prompt-message-id",
        "assistant-message-id",
        "assistant-before-message-id",
        "assistant-before-id",
        "terminal-evidence",
        "unresolved-baseline-user-id",
        "unresolved-baseline-assistant-id",
        "unresolved-baseline-user-count",
        "unresolved-baseline-assistant-count",
        "unresolved-baseline-error-alert-occurrences",
    }
)
_TERMINAL_CHECKPOINT_IDENTITY_KEYS = (
    "submission-attempt-id",
    "prompt-text-digest",
    "prompt-message-id",
    "assistant-before-message-id",
    "assistant-before-id",
    "unresolved-baseline-user-id",
    "unresolved-baseline-assistant-id",
    "unresolved-baseline-user-count",
    "unresolved-baseline-assistant-count",
    "unresolved-baseline-error-alert-occurrences",
)
_RECOVERY_IDENTITY_KEYS = frozenset(
    {
        "unresolved-turn-id",
        "unresolved-baseline-user-id",
        "unresolved-baseline-assistant-id",
        "unresolved-baseline-user-count",
        "unresolved-baseline-assistant-count",
        "unresolved-baseline-error-alert-occurrences",
        "prompt-text-digest",
        "submission-attempt-id",
        "submission-recovery-generation",
        "submission-recovery-claim",
    }
)
TERMINAL_SUBMISSION_CHECKPOINT_REMOVE_KEYS = tuple(
    sorted(_RECOVERY_CHECKPOINT_KEYS - {"unresolved-turn-pending", "submission-recovery-claim"})
)
_SUBMISSION_OBSERVATION_STAGE_ORDER = {
    "dispatching": 0,
    "composer-focused": 1,
    "composer-filled": 2,
    "composer-validated": 3,
    "send-intent": 4,
    "send-click-acknowledged": 5,
}


def _validate_submission_observation_progress(
    metadata: dict[str, Any], metadata_update: dict[str, Any], *, request_id: str, session_id: str
) -> None:
    """Reject invalid or regressing content-free submit-stage checkpoints."""
    attempt_id = metadata_update.get("submission-attempt-id")
    if attempt_id is not None and (
        not isinstance(attempt_id, str) or not attempt_id or len(attempt_id) > 64
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="submission observation attempt identity is invalid",
            details={"request-id": request_id, "session-id": session_id},
        )
    existing_attempt_id = metadata.get("submission-attempt-id")
    if (
        attempt_id is not None
        and existing_attempt_id is not None
        and attempt_id != existing_attempt_id
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="submission observation attempt identity cannot change",
            details={"request-id": request_id, "session-id": session_id},
        )
    stage = metadata_update.get("submission-stage")
    if stage is not None and stage not in _SUBMISSION_OBSERVATION_STAGE_ORDER:
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="submission observation stage is invalid",
            details={"request-id": request_id, "session-id": session_id},
        )
    existing_stage = metadata.get("submission-stage")
    if (
        isinstance(stage, str)
        and isinstance(existing_stage, str)
        and stage in _SUBMISSION_OBSERVATION_STAGE_ORDER
        and existing_stage in _SUBMISSION_OBSERVATION_STAGE_ORDER
        and _SUBMISSION_OBSERVATION_STAGE_ORDER[stage]
        < _SUBMISSION_OBSERVATION_STAGE_ORDER[existing_stage]
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="submission observation stage cannot move backwards",
            details={"request-id": request_id, "session-id": session_id},
        )
    send_intent = metadata_update.get("send-intent-ever")
    if send_intent is not None and not isinstance(send_intent, bool):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="submission send-intent latch must be boolean",
            details={"request-id": request_id, "session-id": session_id},
        )
    if metadata.get("send-intent-ever") is True and send_intent is False:
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="submission send-intent latch cannot be cleared",
            details={"request-id": request_id, "session-id": session_id},
        )
    effective_send_intent = (
        send_intent if send_intent is not None else metadata.get("send-intent-ever")
    )
    if (
        isinstance(stage, str)
        and _SUBMISSION_OBSERVATION_STAGE_ORDER[stage] >= _SUBMISSION_OBSERVATION_STAGE_ORDER["send-intent"]
        and effective_send_intent is not True
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="send-intent observation requires the durable send-intent latch",
            details={"request-id": request_id, "session-id": session_id},
        )


def _frozen_identity_mismatch_keys(
    existing: dict[str, Any], update: dict[str, Any]
) -> list[str]:
    """Return names, never values, for frozen identity fields that differ."""
    return sorted(
        key
        for key in _RECOVERY_IDENTITY_KEYS
        if (key in update) != (key in existing)
        or (key in existing and update.get(key) != existing.get(key))
    )


def _terminal_checkpoint_clear_is_proven(
    existing: dict[str, Any], update: dict[str, Any], request_id: str
) -> bool:
    """Validate terminal evidence against the exact persisted checkpoint identity."""
    evidence = update.get("terminal-evidence")
    verification = evidence.get("verification-evidence") if isinstance(evidence, dict) else None
    verification_set = (
        set(verification) if isinstance(verification, (list, tuple, set)) else set()
    )
    digest = update.get("prompt-text-digest")
    return bool(
        existing.get("unresolved-turn-pending") is True
        and existing.get("unresolved-turn-id") == request_id
        and update.get("unresolved-turn-id") == request_id
        and update.get("submission-proven") is True
        and update.get("submission-proof-source") == "provider-user-message"
        and isinstance(digest, str)
        and bool(digest)
        and isinstance(evidence, dict)
        and evidence.get("turn-id") == request_id
        and evidence.get("policy") == "response-complete"
        and {"not-generating", "text-present"}.issubset(verification_set)
        and bool(
            verification_set.intersection(
                {"completion-control", "response-complete-status"}
            )
        )
        and not _frozen_identity_mismatch_keys(existing, update)
    )


_FRESH_SUBMISSION_DEFAULT_REMOVALS = frozenset(
    {
        "submission-proven",
        "prompt-message-id",
        "assistant-message-id",
        "assistant-before-message-id",
        "assistant-before-id",
        "terminal-evidence",
        "prompt-text-digest",
    }
)


def _fresh_checkpoint_removals_are_safe(
    metadata: dict[str, Any],
    metadata_update: dict[str, Any],
    remove_keys: tuple[str, ...],
) -> bool:
    """Allow only absent/default checkpoint cleanup on an unclaimed fresh turn."""
    if any(not isinstance(key, str) for key in remove_keys):
        return False
    removals = set(remove_keys)
    if not removals.issubset(_FRESH_SUBMISSION_DEFAULT_REMOVALS):
        return False
    removable_false_defaults = {
        key
        for key in ("unresolved-turn-pending", "submission-proven")
        if metadata.get(key) is False
    }
    explicitly_false_updates = {
        key
        for key in ("unresolved-turn-pending", "submission-proven")
        if metadata_update.get(key) is False
    }
    conflicting_updates = removals.intersection(metadata_update) - explicitly_false_updates
    existing_evidence = (
        _RECOVERY_CHECKPOINT_KEYS.intersection(removals).intersection(metadata)
        - removable_false_defaults
    )
    return not conflicting_updates and not existing_evidence


# ── v3 grouped-field accessors ──────────────────────────────────────
# provider/timing/policy/activity are omitted entirely when empty (v3
# schema), so every read goes through .get(..., {}) at each level rather
# than assuming the group exists.


def session_provider_id(record: dict[str, Any]) -> str | None:
    return (record.get("provider") or {}).get("provider-id")


def session_model_id(record: dict[str, Any]) -> str | None:
    return (record.get("provider") or {}).get("model-id")


def session_provider_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return dict((record.get("provider") or {}).get("metadata") or {})


_LOAD_BUDGET_KEYS = frozenset({
    "conversation-load-recovery-attempts", "conversation-load-recovery-revision",
})


def owned_conversation_load_budget(
    project_root: Path, session_id: str, request_id: str, *,
    dispatch_owner_epoch: str, worker_id: str, attempt_epoch: int,
    action: str = "read", expected: tuple[int, int] | None = None,
    maximum: int = 0,
) -> tuple[int, int]:
    """Session-authoritative budget CAS, independent of submission-stage CAS.

    Revision survives reset and checkpoint retirement to prevent ABA. A crash
    after this commit conservatively consumes the attempt; request metadata is
    merely an advisory projection and is never the authority for this budget.
    """
    if (
        action not in {"read", "increment", "reset"}
        or type(maximum) is not int or not 0 <= maximum <= 1_000_000
        or type(attempt_epoch) is not int or attempt_epoch < 0
        or not isinstance(dispatch_owner_epoch, str) or not dispatch_owner_epoch
        or not isinstance(worker_id, str) or not worker_id
    ):
        raise ValueError("invalid conversation load budget operation")
    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            _assert_request_dispatch_owner(
                project_root, request_id, session_id,
                dispatch_owner_epoch=dispatch_owner_epoch, worker_id=worker_id,
                attempt_epoch=attempt_epoch,
            )
            record = read_session_record(project_root, session_id)
            metadata = session_provider_metadata(record)
            count = metadata.get("conversation-load-recovery-attempts", 0)
            revision = metadata.get("conversation-load-recovery-revision", 0)
            if (
                type(count) is not int or count < 0
                or type(revision) is not int or revision < 0
                or metadata.get("unresolved-turn-id") not in (None, request_id)
                or (metadata.get("unresolved-turn-pending") is True
                    and metadata.get("unresolved-turn-id") != request_id)
            ):
                raise AudiaGenticError(code="CON-AGW-125", kind="agents", message="conversation load budget has invalid or foreign authority")
            current = (count, revision)
            if action == "read":
                return current
            if (
                not isinstance(expected, tuple) or len(expected) != 2
                or any(type(value) is not int or value < 0 for value in expected)
                or expected != current
                or (action == "increment" and count >= maximum)
            ):
                raise AudiaGenticError(code="CON-AGW-125", kind="agents", message="conversation load budget compare-and-swap rejected")
            updated = (count + 1 if action == "increment" else 0, revision + 1)
            metadata.update(dict(zip(("conversation-load-recovery-attempts", "conversation-load-recovery-revision"), updated)))
            record.setdefault("provider", {})["metadata"] = metadata
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            write_session_record(project_root, record)
            return updated


def update_provider_metadata(
    project_root: Path,
    session_id: str,
    metadata: dict[str, Any],
    *,
    remove_keys: tuple[str, ...] = (),
    request_id: str | None = None,
    dispatch_owner_epoch: str | None = None,
    worker_id: str | None = None,
    attempt_epoch: int | None = None,
    claim_id: str | None = None,
) -> dict[str, Any]:
    """Atomically update provider metadata without changing session identity.

    Recovery fields are delegated to the request-owner-fenced checkpoint
    writer. Terminal cleanup uses ``clear_terminal_submission_checkpoint``;
    ordinary provider binding metadata remains independent of turn state.
    """
    # Budget changes have their own owner-fenced CAS. Ignore stale projections.
    metadata = {key: value for key, value in metadata.items() if key not in _LOAD_BUDGET_KEYS}
    remove_keys = tuple(key for key in remove_keys if key not in _LOAD_BUDGET_KEYS)
    checkpoint_touched = bool(
        _RECOVERY_CHECKPOINT_KEYS.intersection(metadata)
        or _RECOVERY_CHECKPOINT_KEYS.intersection(remove_keys)
    )
    if checkpoint_touched:
        if not (
            isinstance(request_id, str)
            and request_id
            and isinstance(dispatch_owner_epoch, str)
            and dispatch_owner_epoch
            and isinstance(worker_id, str)
            and worker_id
            and isinstance(attempt_epoch, int)
        ):
            raise AudiaGenticError(
                code="CON-AGW-125",
                kind="agents",
                message="provider recovery checkpoint requires its request-owner fence",
                details={"session-id": session_id},
            )
        return update_owned_submission_checkpoint(
            project_root,
            session_id,
            request_id,
            metadata,
            claim_id=claim_id,
            dispatch_owner_epoch=dispatch_owner_epoch,
            worker_id=worker_id,
            attempt_epoch=attempt_epoch,
            remove_keys=remove_keys,
        )
    with _ordered_session_mutation_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        provider = record.setdefault("provider", {})
        current = dict(provider.get("metadata") or {})
        current.update(metadata)
        for key in remove_keys:
            current.pop(key, None)
        if current:
            provider["metadata"] = current
        else:
            provider.pop("metadata", None)
        record.setdefault("timing", {})["updated-at"] = now_iso_z()
        write_session_record(project_root, record)
        return record


def annotate_owned_manual_reconciliation(
    project_root: Path, session_id: str, request_id: str, *,
    dispatch_owner_epoch: str, worker_id: str, attempt_epoch: int,
) -> None:
    """Record an exhausted observer outcome without changing its turn fence."""
    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            _assert_request_dispatch_owner(
                project_root, request_id, session_id,
                dispatch_owner_epoch=dispatch_owner_epoch,
                worker_id=worker_id, attempt_epoch=attempt_epoch,
            )
            record = read_session_record(project_root, session_id)
            metadata = session_provider_metadata(record)
            if (
                metadata.get("unresolved-turn-pending") is not True
                or metadata.get("unresolved-turn-id") != request_id
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125", kind="agents",
                    message="manual reconciliation annotation requires the current unresolved turn",
                    details={"request-id": request_id, "session-id": session_id},
                )
            metadata["recovery-state"] = "manual-reconcile-required"
            record.setdefault("provider", {})["metadata"] = metadata
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            write_session_record(project_root, record)


def clear_owned_unsent_submission_checkpoint(
    project_root: Path, session_id: str, request_id: str, *,
    submission_attempt_id: str, dispatch_owner_epoch: str,
    worker_id: str, attempt_epoch: int,
) -> None:
    """Retire only the current owner's exact durably pre-Send attempt."""
    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            request = _assert_request_dispatch_owner(
                project_root, request_id, session_id,
                dispatch_owner_epoch=dispatch_owner_epoch,
                worker_id=worker_id, attempt_epoch=attempt_epoch,
            )
            record = read_session_record(project_root, session_id)
            metadata = session_provider_metadata(record)
            if (
                request.get("recovery-required") is True
                or metadata.get("unresolved-turn-id") != request_id
                or metadata.get("unresolved-turn-pending") is not True
                or metadata.get("submission-state") != "dispatching"
                or not isinstance(submission_attempt_id, str)
                or not submission_attempt_id
                or metadata.get("submission-attempt-id") != submission_attempt_id
                or metadata.get("send-intent-ever") is not False
                or metadata.get("submission-proven") is True
                or metadata.get("submission-stage") not in {
                    "dispatching", "composer-focused", "composer-filled", "composer-validated",
                }
                or metadata.get("submission-recovery-claim") is not None
                or metadata.get("submission-recovery-generation") is not None
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125", kind="agents",
                    message="unsent checkpoint retirement requires the exact current no-Send attempt",
                    details={"request-id": request_id, "session-id": session_id},
                )
            for key in _RECOVERY_CHECKPOINT_KEYS:
                metadata.pop(key, None)
            metadata["unresolved-turn-pending"] = False
            record.setdefault("provider", {})["metadata"] = metadata
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            write_session_record(project_root, record)


def clear_terminal_submission_checkpoint(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    recovery_state: str,
    remove_keys: tuple[str, ...],
    expected_metadata: dict[str, Any] | None = None,
) -> bool:
    """Clear a request's session fence only after its durable terminal state.

    The request lock proves the terminal lifecycle while the session mutation
    lock prevents this cleanup from erasing a successor turn's fence.
    """
    with _request_lock(project_root, request_id):
        return _clear_terminal_submission_checkpoint_locked(
            project_root,
            session_id,
            request_id,
            recovery_state=recovery_state,
            remove_keys=remove_keys,
            expected_metadata=expected_metadata,
        )


def _clear_terminal_submission_checkpoint_locked(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    recovery_state: str,
    remove_keys: tuple[str, ...],
    expected_metadata: dict[str, Any] | None = None,
    expected_binding: dict[str, Any] | None = None,
    check_binding: bool = False,
    binding_metadata_update: dict[str, Any] | None = None,
) -> bool:
    """Locked implementation for callers already holding the request lock."""
    from audiagentic.components.agents.gateway import store as gateway_store

    request = gateway_store.read_record(project_root, request_id)
    if (
        request.get("state") not in gateway_store.TERMINAL_STATES
        or request.get("session-id") != session_id
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="provider checkpoint cleanup requires a terminal request bound to the session",
            details={"request-id": request_id, "session-id": session_id},
        )
    allowed_removals = _RECOVERY_CHECKPOINT_KEYS - {
        "unresolved-turn-pending",
        "submission-recovery-claim",
    }
    if not set(remove_keys).issubset(allowed_removals):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="terminal provider checkpoint cleanup contains unsupported fields",
            details={"request-id": request_id, "session-id": session_id},
        )
    if binding_metadata_update and not set(binding_metadata_update).issubset(
        {"chat-url", "provider-session-id", "project-url", "chat-title", "target-id"}
    ):
        raise AudiaGenticError(
            code="CON-AGW-125", kind="agents",
            message="terminal checkpoint binding update contains unsupported fields",
            details={"request-id": request_id, "session-id": session_id},
        )
    with _ordered_session_mutation_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        if check_binding and record.get("binding") != expected_binding:
            return False
        metadata = session_provider_metadata(record)
        current_turn_id = metadata.get("unresolved-turn-id")
        if current_turn_id != request_id:
            return False
        if expected_metadata is not None:
            # A request id can be reused across a prepared-submission recovery
            # attempt. Compare the complete persisted checkpoint snapshot so a
            # delayed predecessor finalizer cannot clear a successor attempt
            # with the same logical turn id but a new generation/claim/stage.
            if any(
                (key in expected_metadata) != (key in metadata)
                or (
                    key in expected_metadata
                    and expected_metadata.get(key) != metadata.get(key)
                )
                for key in _RECOVERY_CHECKPOINT_KEYS
            ):
                return False
        metadata["unresolved-turn-pending"] = False
        metadata["recovery-state"] = recovery_state
        for key in remove_keys:
            metadata.pop(key, None)
        metadata.update(binding_metadata_update or {})
        record.setdefault("provider", {})["metadata"] = metadata
        record.setdefault("timing", {})["updated-at"] = now_iso_z()
        write_session_record(project_root, record)
    return True


def clear_completed_checkpoint_residue(
    project_root: Path,
    session_id: str,
    terminal_request_id: str,
    *,
    expected_metadata: dict[str, Any],
    expected_binding_identity: dict[str, Any],
    allow_orphaned_pending: bool = False,
) -> bool:
    """Remove stale terminal checkpoint fields after proving their owner.

    Legacy non-pending residue is accepted by default. The explicit orphaned
    mode also accepts ``pending=True`` only when the owner turn id is absent;
    its private attempt id must fingerprint-match terminal evidence on the
    completed predecessor. Both modes require a readable response artifact,
    immutable session binding identity, and a full checkpoint snapshot CAS
    under request -> retention -> session lock order.
    """
    from audiagentic.components.agents.gateway import store as gateway_store

    expected_attempt_id = expected_metadata.get("submission-attempt-id")
    pending_false_residue = (
        expected_metadata.get("unresolved-turn-pending") is False
        and not expected_metadata.get("unresolved-turn-id")
    )
    orphaned_pending = (
        allow_orphaned_pending
        and expected_metadata.get("unresolved-turn-pending") is True
        and not expected_metadata.get("unresolved-turn-id")
        and expected_metadata.get("submission-recovery-claim") is None
        and expected_metadata.get("submission-recovery-generation") is None
    )
    if (
        not (pending_false_residue or orphaned_pending)
        or not isinstance(expected_attempt_id, str)
        or not expected_attempt_id
    ):
        return False
    expected_attempt_fingerprint = hashlib.sha256(
        expected_attempt_id.encode("utf-8")
    ).hexdigest()

    with _request_lock(project_root, terminal_request_id):
        request = gateway_store.read_record(
            project_root, terminal_request_id, include_output=False
        )
        request_metadata = request.get("provider-metadata")
        request_metadata = request_metadata if isinstance(request_metadata, dict) else {}
        terminal_evidence = request_metadata.get("terminal-evidence")
        terminal_evidence = terminal_evidence if isinstance(terminal_evidence, dict) else {}
        request_attempt_id = request_metadata.get("submission-attempt-id")
        artifact = request.get("response-artifact")
        evidence_proves_attempt = (
            terminal_evidence.get("turn-id") == terminal_request_id
            and terminal_evidence.get("policy") == "response-complete"
            and isinstance(terminal_evidence.get("terminal-witness-id"), str)
            and bool(terminal_evidence.get("terminal-witness-id"))
            and terminal_evidence.get("submission-attempt-fingerprint")
            == expected_attempt_fingerprint
        )
        expected_checkpoint_fingerprint = _terminal_checkpoint_fingerprint(
            expected_metadata, turn_id=terminal_request_id
        )
        checkpoint_fingerprint = terminal_evidence.get(
            "submission-checkpoint-fingerprint"
        )
        evidence_proves_checkpoint_identity = (
            expected_checkpoint_fingerprint is not None
            and checkpoint_fingerprint == expected_checkpoint_fingerprint
        )
        checkpoint_identity_conflicts = (
            checkpoint_fingerprint is not None
            and not evidence_proves_checkpoint_identity
        )
        if (
            request.get("state") != "completed"
            or request.get("session-id") != session_id
            or (
                request_attempt_id is not None
                and request_attempt_id != expected_attempt_id
            )
            or not (
                request_attempt_id == expected_attempt_id
                or evidence_proves_attempt
            )
            or checkpoint_identity_conflicts
            or (
                orphaned_pending
                and (
                    not evidence_proves_attempt
                    or not evidence_proves_checkpoint_identity
                )
            )
            or not isinstance(artifact, dict)
            or artifact.get("request-id") != terminal_request_id
        ):
            return False
        from audiagentic.components.agents.gateway.output import read_final_response

        # Request locks protect artifact writes; the retention lock protects
        # archived-request removal. Hold both while re-reading the immutable
        # terminal reference and validating its bytes, then acquire the
        # session lock in the established request -> retention -> session
        # order before the checkpoint CAS.
        with StartupLock(gateway_retention_lock_path(project_root)):
            try:
                current_request = gateway_store.read_record(
                    project_root, terminal_request_id, include_output=False
                )
                current_artifact = current_request.get("response-artifact")
                if (
                    current_request.get("state") != "completed"
                    or current_request.get("session-id") != session_id
                    or current_request.get("provider-metadata", {}).get(
                        "submission-attempt-id"
                    ) not in {None, expected_attempt_id}
                    or current_artifact != artifact
                ):
                    return False
                current_terminal_evidence = current_request.get(
                    "provider-metadata", {}
                ).get("terminal-evidence")
                current_terminal_evidence = (
                    current_terminal_evidence
                    if isinstance(current_terminal_evidence, dict)
                    else {}
                )
                current_evidence_proves_attempt = (
                    current_terminal_evidence.get("turn-id") == terminal_request_id
                    and current_terminal_evidence.get("policy") == "response-complete"
                    and isinstance(
                        current_terminal_evidence.get("terminal-witness-id"), str
                    )
                    and bool(current_terminal_evidence.get("terminal-witness-id"))
                    and current_terminal_evidence.get(
                        "submission-attempt-fingerprint"
                    )
                    == expected_attempt_fingerprint
                )
                current_checkpoint_fingerprint = _terminal_checkpoint_fingerprint(
                    expected_metadata, turn_id=terminal_request_id
                )
                current_evidence_checkpoint_fingerprint = (
                    current_terminal_evidence.get("submission-checkpoint-fingerprint")
                )
                current_evidence_proves_checkpoint_identity = (
                    current_checkpoint_fingerprint is not None
                    and current_evidence_checkpoint_fingerprint
                    == current_checkpoint_fingerprint
                )
                if (
                    request_attempt_id != expected_attempt_id
                    and not current_evidence_proves_attempt
                ):
                    return False
                if (
                    current_evidence_checkpoint_fingerprint is not None
                    and not current_evidence_proves_checkpoint_identity
                ):
                    return False
                if orphaned_pending and (
                    not current_evidence_proves_attempt
                    or not current_evidence_proves_checkpoint_identity
                ):
                    return False
                response = read_final_response(
                    project_root, terminal_request_id, current_artifact
                )
            except (AudiaGenticError, OSError, TypeError, ValueError, AttributeError):
                return False
            if not isinstance(response, str) or not response.strip():
                return False

            with _session_lock(project_root, session_id):
                record = read_session_record(project_root, session_id)
                metadata = session_provider_metadata(record)
                binding = record.get("binding")
                if (
                    record.get("state") not in {"active", "failed"}
                    or not isinstance(binding, dict)
                    or binding.get("binding-id")
                    != expected_binding_identity.get("binding-id")
                    or binding.get("generation")
                    != expected_binding_identity.get("generation")
                    or metadata.get("unresolved-turn-pending")
                    is not expected_metadata.get("unresolved-turn-pending")
                    or metadata.get("unresolved-turn-id")
                    or metadata.get("submission-recovery-claim") is not None
                    or (
                        orphaned_pending
                        and metadata.get("submission-recovery-generation") is not None
                    )
                    or metadata.get("submission-attempt-id") != expected_attempt_id
                    or any(
                        (key in expected_metadata) != (key in metadata)
                        or (
                            key in expected_metadata
                            and expected_metadata.get(key) != metadata.get(key)
                        )
                        for key in _RECOVERY_CHECKPOINT_KEYS
                    )
                ):
                    return False
                for key in _RECOVERY_CHECKPOINT_KEYS - {
                    "unresolved-turn-pending",
                    "submission-recovery-claim",
                }:
                    metadata.pop(key, None)
                if orphaned_pending:
                    metadata["unresolved-turn-pending"] = False
                metadata["recovery-state"] = (
                    "orphaned-terminal-fence-cleared"
                    if orphaned_pending
                    else "stale-terminal-checkpoint-residue-cleared"
                )
                record.setdefault("provider", {})["metadata"] = metadata
                record.setdefault("timing", {})["updated-at"] = now_iso_z()
                write_session_record(project_root, record)
    return True


def _assert_request_dispatch_owner(
    project_root: Path,
    request_id: str,
    session_id: str,
    *,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    allow_queued_pre_send: bool = False,
) -> dict[str, Any]:
    from audiagentic.components.agents.gateway import store as gateway_store

    request = gateway_store.read_record(project_root, request_id)
    request_state = request.get("state")
    request_is_owned = (
        request_state == "running"
        or (
            allow_queued_pre_send
            and request_state == "queued"
            and request.get("recovery-required") is not True
        )
    )
    owner_facts = {
        "request-state-owned": request_is_owned,
        "session-id-matches": request.get("session-id") == session_id,
        "dispatch-owner-epoch-matches": (
            request.get("dispatch-owner-epoch") == dispatch_owner_epoch
        ),
        "worker-id-matches": request.get("worker-id") == worker_id,
        "attempt-epoch-matches": request.get("attempt-epoch") == attempt_epoch,
        "allow-queued-pre-send": allow_queued_pre_send,
        "recovery-required": request.get("recovery-required") is True,
    }
    if not all(
        owner_facts[key]
        for key in (
            "request-state-owned",
            "session-id-matches",
            "dispatch-owner-epoch-matches",
            "worker-id-matches",
            "attempt-epoch-matches",
        )
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="prepared submission recovery lost its request owner fence",
            details={
                "request-id": request_id,
                "session-id": session_id,
                "request-owner-fence": owner_facts,
            },
        )
    session = read_session_record(project_root, session_id)
    if session_provider_id(session) == "gpt-auto":
        from audiagentic.components.providers.adapters.gpt_auto.urls import parse_project_id

        request_metadata = request.get("provider-metadata")
        request_metadata = request_metadata if isinstance(request_metadata, dict) else {}
        session_metadata = session_provider_metadata(session)
        request_project_id = request.get("project-id") or request_metadata.get("project-id")
        if not isinstance(request_project_id, str) or not request_project_id:
            request_project_id = parse_project_id(
                str(request_metadata.get("project-url") or request_metadata.get("chat-url") or "")
            )
        session_project_id = session_metadata.get("project-id")
        if not isinstance(session_project_id, str) or not session_project_id:
            session_project_id = parse_project_id(
                str(session_metadata.get("project-url") or session_metadata.get("chat-url") or "")
            )
        if (
            not isinstance(request_project_id, str)
            or not request_project_id
            or not isinstance(session_project_id, str)
            or not session_project_id
            or request_project_id != session_project_id
        ):
            raise AudiaGenticError(
                code="CON-AGW-125",
                kind="agents",
                message="prepared recovery request and session do not prove the same GPT project",
                details={"request-id": request_id, "session-id": session_id},
            )
    return request


def claim_prepared_submission_recovery(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    lease_seconds: float = 180.0,
) -> dict[str, Any]:
    """Claim a proven-unsent checkpoint under request and cross-process locks.

    The prepared checkpoint remains intact while a replacement provider
    surface is being opened. A crash therefore leaves recoverable proof; the
    request-owner fencing lets a successor take over immediately. An expired
    same-owner claim can also be reclaimed after a crashed worker, with a new
    generation fencing any late writes from the old claimant.
    """
    from audiagentic.components.agents.gateway.store._shared import _request_lock

    with _request_lock(project_root, request_id):
        _assert_request_dispatch_owner(
            project_root,
            request_id,
            session_id,
            dispatch_owner_epoch=dispatch_owner_epoch,
            worker_id=worker_id,
            attempt_epoch=attempt_epoch,
            allow_queued_pre_send=True,
        )
        with _ordered_session_mutation_lock(project_root, session_id):
            record = read_session_record(project_root, session_id)
            metadata = session_provider_metadata(record)
            if not (
                record.get("state") == "active"
                and metadata.get("unresolved-turn-pending") is True
                and metadata.get("unresolved-turn-id") == request_id
                and metadata.get("submission-state") == "prepared"
                and metadata.get("submission-proven") is False
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="prepared submission checkpoint changed before recovery claim",
                    details={"request-id": request_id, "session-id": session_id},
                )
            previous = metadata.get("submission-recovery-claim")
            generation = metadata.get("submission-recovery-generation", 0)
            if isinstance(previous, dict):
                previous_owner = (
                    previous.get("dispatch-owner-epoch"),
                    previous.get("worker-id"),
                    previous.get("attempt-epoch"),
                )
                current_owner = (dispatch_owner_epoch, worker_id, attempt_epoch)
                if previous_owner == current_owner:
                    expires = previous.get("lease-expires-at")
                    try:
                        expired = (
                            datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                            <= datetime.now(timezone.utc)
                        )
                    except (TypeError, ValueError):
                        expired = False
                    if not expired:
                        raise AudiaGenticError(
                            code="CON-AGW-125",
                            kind="agents",
                            message="prepared submission recovery is already claimed",
                            details={"request-id": request_id, "session-id": session_id},
                        )
                generation = max(generation, previous.get("generation", 0))
            try:
                generation = max(0, int(generation)) + 1
            except (TypeError, ValueError):
                generation = 1
            claim = {
                "claim-id": uuid.uuid4().hex,
                "generation": generation,
                "dispatch-owner-epoch": dispatch_owner_epoch,
                "worker-id": worker_id,
                "attempt-epoch": attempt_epoch,
                "lease-expires-at": (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=max(1.0, lease_seconds))
                ).isoformat().replace("+00:00", "Z"),
            }
            provider = record.setdefault("provider", {})
            metadata["submission-recovery-claim"] = claim
            metadata["submission-recovery-generation"] = generation
            provider["metadata"] = metadata
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            write_session_record(project_root, record)
            return claim


def _assert_prepared_submission_claim_locked(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    claim_id: str,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _assert_request_dispatch_owner(
        project_root,
        request_id,
        session_id,
        dispatch_owner_epoch=dispatch_owner_epoch,
        worker_id=worker_id,
        attempt_epoch=attempt_epoch,
        allow_queued_pre_send=True,
    )
    record = read_session_record(project_root, session_id)
    metadata = session_provider_metadata(record)
    claim = metadata.get("submission-recovery-claim")
    if not (
        metadata.get("unresolved-turn-pending") is True
        and metadata.get("unresolved-turn-id") == request_id
        and metadata.get("submission-state") == "prepared"
        and metadata.get("submission-proven") is False
        and isinstance(claim, dict)
        and claim.get("claim-id") == claim_id
        and claim.get("dispatch-owner-epoch") == dispatch_owner_epoch
        and claim.get("worker-id") == worker_id
        and claim.get("attempt-epoch") == attempt_epoch
        and claim.get("generation") == metadata.get("submission-recovery-generation")
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="prepared submission recovery claim was lost before provider action",
            details={"request-id": request_id, "session-id": session_id},
        )
    return record, metadata


def assert_prepared_submission_recovery_claim(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    claim_id: str,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
) -> None:
    from audiagentic.components.agents.gateway.store._shared import _request_lock

    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            _assert_prepared_submission_claim_locked(
                project_root,
                session_id,
                request_id,
                claim_id=claim_id,
                dispatch_owner_epoch=dispatch_owner_epoch,
                worker_id=worker_id,
                attempt_epoch=attempt_epoch,
            )


def advance_prepared_submission_to_dispatching(
    project_root: Path,
    session_id: str,
    request_id: str,
    metadata_update: dict[str, Any],
    *,
    claim_id: str,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    remove_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """CAS prepared -> dispatching and consume its recovery claim atomically."""
    from audiagentic.components.agents.gateway.store._shared import _request_lock

    if {"submission-recovery-claim", "submission-recovery-generation"}.intersection(
        metadata_update
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="provider checkpoint cannot replace recovery claim identity",
            details={"request-id": request_id, "session-id": session_id},
        )
    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            record, metadata = _assert_prepared_submission_claim_locked(
                project_root,
                session_id,
                request_id,
                claim_id=claim_id,
                dispatch_owner_epoch=dispatch_owner_epoch,
                worker_id=worker_id,
                attempt_epoch=attempt_epoch,
            )
            if metadata_update.get("submission-state") != "dispatching":
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="prepared recovery may only advance to dispatching",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if (
                metadata_update.get("unresolved-turn-pending") is not True
                or metadata_update.get("unresolved-turn-id") != request_id
                or metadata_update.get("submission-proven") is True
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="dispatching checkpoint does not preserve the unsent request identity",
                    details={"request-id": request_id, "session-id": session_id},
                )
            for key in _RECOVERY_IDENTITY_KEYS:
                if (
                    key in metadata_update
                    and key in metadata
                    and metadata_update[key] != metadata[key]
                ):
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="dispatching checkpoint cannot replace frozen turn identity",
                        details={"request-id": request_id, "session-id": session_id},
                    )
            if not _fresh_checkpoint_removals_are_safe(
                metadata, metadata_update, remove_keys
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="prepared recovery removal is not limited to absent/default fields",
                    details={
                        "request-id": request_id,
                        "session-id": session_id,
                        "checkpoint-diagnostics": {
                            "removal-count": len(remove_keys),
                            "protected-removal-count": len(
                                _RECOVERY_CHECKPOINT_KEYS.intersection(remove_keys)
                            ),
                            "removal-conflicts-with-update": bool(
                                set(remove_keys).intersection(metadata_update)
                                - {
                                    key
                                    for key in ("unresolved-turn-pending", "submission-proven")
                                    if metadata_update.get(key) is False
                                }
                            ),
                        },
                    },
                )
            _validate_submission_observation_progress(
                metadata,
                metadata_update,
                request_id=request_id,
                session_id=session_id,
            )
            metadata.update(metadata_update)
            for key in (*remove_keys, "submission-recovery-claim"):
                metadata.pop(key, None)
            record.setdefault("provider", {})["metadata"] = metadata
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            write_session_record(project_root, record)
            return record


def update_prepared_submission_checkpoint(
    project_root: Path,
    session_id: str,
    request_id: str,
    metadata_update: dict[str, Any],
    *,
    claim_id: str,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    remove_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Compatibility wrapper for the common owner-validated checkpoint path."""
    return update_owned_submission_checkpoint(
        project_root,
        session_id,
        request_id,
        metadata_update,
        claim_id=claim_id,
        dispatch_owner_epoch=dispatch_owner_epoch,
        worker_id=worker_id,
        attempt_epoch=attempt_epoch,
        remove_keys=remove_keys,
    )


def update_owned_submission_checkpoint(
    project_root: Path,
    session_id: str,
    request_id: str,
    metadata_update: dict[str, Any],
    *,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    claim_id: str | None = None,
    remove_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Update recovery checkpoint only under its request owner and current stage."""
    metadata_update = {key: value for key, value in metadata_update.items() if key not in _LOAD_BUDGET_KEYS}
    remove_keys = tuple(key for key in remove_keys if key not in _LOAD_BUDGET_KEYS)
    if {"submission-recovery-claim", "submission-recovery-generation"}.intersection(
        metadata_update
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="provider checkpoint cannot replace recovery claim identity",
            details={"request-id": request_id, "session-id": session_id},
        )
    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            record = read_session_record(project_root, session_id)
            metadata = session_provider_metadata(record)
            current_stage = metadata.get("submission-state")
            cleared_annotation_keys = (
                {"recovery-state"}
                if metadata.get("recovery-state") in {
                    "terminal-captured", "stale-terminal-checkpoint-residue-cleared",
                    "orphaned-terminal-fence-cleared",
                }
                else set()
            )
            fresh_prepared_checkpoint = (
                current_stage is None
                and metadata.get("unresolved-turn-pending") is not True
                and not (
                    _RECOVERY_IDENTITY_KEYS.intersection(metadata)
                    - {"unresolved-baseline-error-alert-occurrences"}
                )
                and not (
                    _RECOVERY_CHECKPOINT_KEYS.intersection(metadata)
                    - {"unresolved-turn-pending", "submission-proven", "unresolved-baseline-error-alert-occurrences"}
                    - cleared_annotation_keys
                )
                and (
                    "unresolved-baseline-error-alert-occurrences" not in metadata
                    or metadata.get("unresolved-baseline-error-alert-occurrences") == []
                )
                # Initial provider binding metadata may explicitly carry the
                # default false value before the first turn is admitted. That
                # is absence of submission proof, not prior-turn evidence.
                and (
                    metadata.get("submission-proven") is None
                    or metadata.get("submission-proven") is False
                )
                and metadata_update.get("submission-state") == "prepared"
                and metadata_update.get("unresolved-turn-pending") is True
                and metadata_update.get("unresolved-turn-id") == request_id
                and metadata_update.get("submission-proven") is False
                and claim_id is None
            )
            fresh_prepared_dispatch = (
                current_stage == "prepared"
                and claim_id is None
                and metadata.get("submission-recovery-claim") is None
                and metadata.get("submission-recovery-generation") is None
            )
            dispatching_to_proven_checkpoint = False
            if fresh_prepared_checkpoint:
                # The first turn on a newly admitted session has no prior
                # checkpoint (and therefore no recovery claim). The durable
                # request owner is the authority for this one-way initialization.
                request = _assert_request_dispatch_owner(
                    project_root,
                    request_id,
                    session_id,
                    dispatch_owner_epoch=dispatch_owner_epoch,
                    worker_id=worker_id,
                    attempt_epoch=attempt_epoch,
                )
                if request.get("recovery-required") is True:
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="recovered request requires a prepared submission claim",
                        details={"request-id": request_id, "session-id": session_id},
                    )
                removable_initial_defaults = {
                    key
                    for key in ("unresolved-turn-pending", "submission-proven")
                    if metadata.get(key) is False
                }
                existing_recovery_removals = (
                    _RECOVERY_CHECKPOINT_KEYS.intersection(remove_keys)
                    .intersection(metadata)
                    - removable_initial_defaults
                )
                if existing_recovery_removals:
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="initial prepared checkpoint cannot remove recovery evidence",
                        details={"request-id": request_id, "session-id": session_id},
                    )
            elif fresh_prepared_dispatch:
                # The normal first-turn dispatch advances its just-written
                # prepared checkpoint without a recovery claim. A takeover
                # marks the durable request recovery-required, so restarted
                # owners must instead acquire the prepared recovery claim.
                request = _assert_request_dispatch_owner(
                    project_root,
                    request_id,
                    session_id,
                    dispatch_owner_epoch=dispatch_owner_epoch,
                    worker_id=worker_id,
                    attempt_epoch=attempt_epoch,
                )
                if (
                    request.get("recovery-required") is True
                    or metadata.get("submission-recovery-claim") is not None
                    or metadata.get("submission-recovery-generation") is not None
                    or metadata.get("unresolved-turn-pending") is not True
                    or metadata.get("unresolved-turn-id") != request_id
                    or not (
                        metadata.get("submission-proven") is None
                        or metadata.get("submission-proven") is False
                    )
                    or metadata_update.get("submission-state") != "dispatching"
                    or metadata_update.get("unresolved-turn-pending") is not True
                    or metadata_update.get("unresolved-turn-id") != request_id
                    or metadata_update.get("submission-proven") is True
                ):
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="fresh prepared checkpoint cannot advance without its request owner",
                        details={"request-id": request_id, "session-id": session_id},
                    )
            elif current_stage == "prepared":
                if not isinstance(claim_id, str) or not claim_id:
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="prepared checkpoint update requires its recovery claim",
                        details={"request-id": request_id, "session-id": session_id},
                    )
                record, metadata = _assert_prepared_submission_claim_locked(
                    project_root,
                    session_id,
                    request_id,
                    claim_id=claim_id,
                    dispatch_owner_epoch=dispatch_owner_epoch,
                    worker_id=worker_id,
                    attempt_epoch=attempt_epoch,
                )
            else:
                dispatch_request = _assert_request_dispatch_owner(
                    project_root,
                    request_id,
                    session_id,
                    dispatch_owner_epoch=dispatch_owner_epoch,
                    worker_id=worker_id,
                    attempt_epoch=attempt_epoch,
                )
                prompt_message_id = metadata_update.get("prompt-message-id")
                prompt_text_digest = metadata.get("prompt-text-digest")
                baseline_user_count = metadata.get("unresolved-baseline-user-count")
                baseline_user_id = metadata.get("unresolved-baseline-user-id")
                baseline_assistant_count = metadata.get(
                    "unresolved-baseline-assistant-count"
                )
                proof_update_keys_are_safe = set(metadata_update).issubset(
                    _RECOVERY_CHECKPOINT_KEYS | {"target-id"}
                )
                frozen_identity_mismatch_keys = _frozen_identity_mismatch_keys(
                    metadata, metadata_update
                )
                frozen_identity_is_unchanged = not frozen_identity_mismatch_keys
                prompt_message_id_is_durable = (
                    isinstance(prompt_message_id, str)
                    and bool(prompt_message_id.strip())
                    and not prompt_message_id.startswith(
                        ("fallback-", "virtualized-prompt-for-")
                    )
                )
                prompt_digest_matches = (
                    isinstance(prompt_text_digest, str)
                    and bool(prompt_text_digest)
                    and metadata_update.get("prompt-text-digest") == prompt_text_digest
                )
                baseline_user_count_matches = (
                    isinstance(baseline_user_count, int)
                    and not isinstance(baseline_user_count, bool)
                    and metadata_update.get("unresolved-baseline-user-count")
                    == baseline_user_count
                )
                baseline_assistant_count_matches = (
                    isinstance(baseline_assistant_count, int)
                    and not isinstance(baseline_assistant_count, bool)
                    and metadata_update.get("unresolved-baseline-assistant-count")
                    == baseline_assistant_count
                )
                baseline_user_id_is_new = (
                    not isinstance(baseline_user_id, str)
                    or prompt_message_id != baseline_user_id
                )
                request_owner_is_current = (
                    dispatch_request.get("recovery-required") is not True
                )
                dispatching_to_proven_checkpoint = (
                    current_stage == "dispatching"
                    and claim_id is None
                    and metadata.get("unresolved-turn-pending") is True
                    and metadata.get("unresolved-turn-id") == request_id
                    and (
                        metadata.get("submission-proven") is None
                        or metadata.get("submission-proven") is False
                    )
                    and metadata.get("submission-recovery-claim") is None
                    and metadata.get("submission-recovery-generation") is None
                    and metadata_update.get("submission-state") == "proven"
                    and metadata_update.get("unresolved-turn-pending") is True
                    and metadata_update.get("unresolved-turn-id") == request_id
                    and metadata_update.get("submission-proven") is True
                    and metadata_update.get("submission-proof-source")
                    == "provider-user-message"
                    and proof_update_keys_are_safe
                    and frozen_identity_is_unchanged
                    and prompt_message_id_is_durable
                    and prompt_digest_matches
                    and baseline_user_count_matches
                    and baseline_assistant_count_matches
                    and baseline_user_id_is_new
                    and request_owner_is_current
                )
                if not (
                    metadata.get("unresolved-turn-pending") is True
                    and metadata.get("unresolved-turn-id") == request_id
                    and current_stage in {None, "dispatching"}
                    and claim_id is None
                    and (
                        metadata_update.get("submission-state") != "proven"
                        or dispatching_to_proven_checkpoint
                    )
                ):
                    known_stages = {"prepared", "dispatching", "proven", "cleared"}
                    requested_stage = metadata_update.get("submission-state")
                    observed_proof = metadata.get("submission-proven")
                    error_details = {
                        "request-id": request_id,
                        "session-id": session_id,
                        "checkpoint-diagnostics": {
                            "observed-stage": (
                                current_stage
                                if current_stage is None
                                or (
                                    isinstance(current_stage, str)
                                    and current_stage in known_stages
                                )
                                else "other"
                            ),
                            "requested-stage": (
                                requested_stage
                                if requested_stage is None
                                or (
                                    isinstance(requested_stage, str)
                                    and requested_stage in known_stages
                                )
                                else "other"
                            ),
                            "unresolved-turn-pending": (
                                metadata.get("unresolved-turn-pending") is True
                            ),
                            "turn-id-matches-request": (
                                metadata.get("unresolved-turn-id") == request_id
                            ),
                            "claim-id-supplied": claim_id is not None,
                            "claim-present": metadata.get(
                                "submission-recovery-claim"
                            )
                            is not None,
                            "claim-generation-present": metadata.get(
                                "submission-recovery-generation"
                            )
                            is not None,
                            "submission-proven": (
                                observed_proof
                                if isinstance(observed_proof, bool)
                                else "missing-or-invalid"
                            ),
                            "request-recovery-required": (
                                dispatch_request.get("recovery-required") is True
                            ),
                            "proof-source-valid": (
                                metadata_update.get("submission-proof-source")
                                == "provider-user-message"
                            ),
                            "proof-update-keys-safe": proof_update_keys_are_safe,
                            "frozen-identity-unchanged": frozen_identity_is_unchanged,
                            "frozen-identity-mismatch-keys": frozen_identity_mismatch_keys,
                            "provider-anchor-valid": prompt_message_id_is_durable,
                            "fingerprint-equal": prompt_digest_matches,
                            "baseline-user-count-matches": baseline_user_count_matches,
                            "baseline-assistant-count-matches": baseline_assistant_count_matches,
                            "baseline-user-id-is-new": baseline_user_id_is_new,
                            "request-owner-is-current": request_owner_is_current,
                        },
                    }
                    previous_turn_blocks_prepared = (
                        requested_stage == "prepared"
                        and metadata.get("unresolved-turn-pending") is True
                        and metadata.get("unresolved-turn-id") != request_id
                        and metadata.get("submission-recovery-claim") is None
                        and metadata.get("submission-recovery-generation") is None
                        and request_owner_is_current
                    )
                    if previous_turn_blocks_prepared:
                        # The prepared stage is rejected before provider Send.
                        # Keep this request in reconciliation instead of
                        # terminal-failing it as a generic checkpoint error.
                        error_details.update(
                            {
                                "failure-stage": "submission",
                                "submission-state": "not_started",
                                "submission-proven": False,
                                "submission-ambiguous": False,
                                "previous-turn-unresolved": True,
                            }
                        )
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="owned checkpoint update does not match the current dispatch stage",
                        details=error_details,
                    )
            if "submission-state" in metadata_update and (
                metadata_update["submission-state"] != "dispatching"
                or metadata.get("submission-state")
                not in {None, "dispatching"}
            ) and not (
                fresh_prepared_checkpoint
                or fresh_prepared_dispatch
                or dispatching_to_proven_checkpoint
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="owned checkpoint update cannot change submission stage",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if "unresolved-turn-id" in metadata_update and metadata_update[
                "unresolved-turn-id"
            ] != request_id:
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="owned checkpoint update cannot change its request identity",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if metadata.get("submission-state") == "prepared" and metadata_update.get(
                "submission-proven"
            ) is True:
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="prepared checkpoint cannot claim a submitted prompt",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if (
                metadata.get("submission-state") == "prepared"
                and metadata_update.get("unresolved-turn-pending") is False
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="prepared checkpoint cannot be completed before dispatch",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if metadata_update.get("unresolved-turn-pending") is False:
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="running request cannot clear its recovery checkpoint",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if (
                metadata.get("submission-proven") is True
                and metadata_update.get("submission-proven") is False
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="submission proof cannot regress from proven to unproven",
                    details={"request-id": request_id, "session-id": session_id},
                )
            for key in _RECOVERY_IDENTITY_KEYS:
                if (
                    key in metadata_update
                    and key in metadata
                    and metadata_update[key] != metadata[key]
                ):
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="owned checkpoint update cannot replace frozen turn identity",
                        details={"request-id": request_id, "session-id": session_id},
                    )
            protected_removals = _RECOVERY_CHECKPOINT_KEYS.intersection(remove_keys)
            fresh_prepared_removal_safe = (
                (fresh_prepared_checkpoint or fresh_prepared_dispatch)
                and _fresh_checkpoint_removals_are_safe(
                    metadata, metadata_update, remove_keys
                )
            )
            if (
                (fresh_prepared_checkpoint or fresh_prepared_dispatch)
                and not fresh_prepared_removal_safe
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="fresh checkpoint cleanup exceeds the absent/default allowlist",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if (
                metadata.get("submission-state") == "prepared"
                and protected_removals
                and not fresh_prepared_removal_safe
            ):
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="prepared recovery evidence cannot be removed before dispatch",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if protected_removals and not fresh_prepared_removal_safe:
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="recovery evidence removal requires a terminal request",
                    details={"request-id": request_id, "session-id": session_id},
                )
            _validate_submission_observation_progress(
                metadata,
                metadata_update,
                request_id=request_id,
                session_id=session_id,
            )
            metadata.update(metadata_update)
            for key in remove_keys:
                metadata.pop(key, None)
            record.setdefault("provider", {})["metadata"] = metadata
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            write_session_record(project_root, record)
            return record


def install_prepared_recovery_binding(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    provider_id: str,
    surface_id: str,
    provider_session_ref: str,
    claim_id: str,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    expected_surface_id: str,
    binding_metadata: dict[str, Any] | None = None,
    binding_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Install a newly opened provider identity under the prepared recovery claim."""
    from audiagentic.components.agents.gateway.store._shared import _request_lock

    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            record, metadata = _assert_prepared_submission_claim_locked(
                project_root,
                session_id,
                request_id,
                claim_id=claim_id,
                dispatch_owner_epoch=dispatch_owner_epoch,
                worker_id=worker_id,
                attempt_epoch=attempt_epoch,
            )
            admitted_provider = session_provider_id(record)
            if admitted_provider and admitted_provider != provider_id:
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="prepared provider binding conflicts with admitted provider",
                    details={"session-id": session_id},
                )
            if not isinstance(expected_surface_id, str) or not expected_surface_id.strip() or surface_id != expected_surface_id:
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="prepared provider binding does not match the admission-frozen surface",
                    details={"session-id": session_id},
                )
            current = record.get("binding")
            if isinstance(current, dict):
                if not (
                    current.get("provider-id") == provider_id
                    and current.get("surface-id") == surface_id
                    and current.get("provider-session-ref") == provider_session_ref
                ):
                    raise AudiaGenticError(
                        code="CON-AGW-120",
                        kind="agents",
                        message="prepared provider binding conflicts with existing session identity",
                        details={"session-id": session_id},
                    )
            else:
                record["binding"] = bindings.build_binding(
                    provider_id=provider_id,
                    provider_session_ref=provider_session_ref,
                    surface_id=surface_id,
                    **(binding_identity or {}),
                )
            if binding_metadata:
                metadata.update(
                    {
                        key: value
                        for key, value in binding_metadata.items()
                        if key not in _RECOVERY_CHECKPOINT_KEYS | _LOAD_BUDGET_KEYS
                    }
                )
            record.setdefault("provider", {})["metadata"] = metadata
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            _validate(record, code="VAL-AGW-120")
            bindings.register_open_binding(project_root, record)
            write_session_record(project_root, record)
            return record


def commit_prepared_recovery_open(
    project_root: Path,
    session_id: str,
    request_id: str,
    opened_record: dict[str, Any],
    *,
    claim_id: str,
    dispatch_owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    expected_surface_id: str,
    on_commit: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Commit provider-open facts without replacing admitted session state or stale ownership."""
    from audiagentic.components.agents.gateway.store._shared import _request_lock

    with _request_lock(project_root, request_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            record, metadata = _assert_prepared_submission_claim_locked(
                project_root,
                session_id,
                request_id,
                claim_id=claim_id,
                dispatch_owner_epoch=dispatch_owner_epoch,
                worker_id=worker_id,
                attempt_epoch=attempt_epoch,
            )
            previous_record = copy.deepcopy(record)
            opened_binding = opened_record.get("binding")
            current_binding = record.get("binding")
            if not isinstance(opened_binding, dict):
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="provider open did not return a durable session binding",
                    details={"session-id": session_id},
                )
            if (
                not isinstance(expected_surface_id, str)
                or not expected_surface_id.strip()
                or opened_binding.get("surface-id") != expected_surface_id
            ):
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="provider-open surface differs from the admission-frozen surface",
                    details={"session-id": session_id},
                )
            if isinstance(current_binding, dict) and not (
                current_binding.get("provider-id") == opened_binding.get("provider-id")
                and current_binding.get("surface-id") == opened_binding.get("surface-id")
                and current_binding.get("provider-session-ref")
                == opened_binding.get("provider-session-ref")
            ):
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="provider-open result conflicts with the committed session binding",
                    details={"session-id": session_id},
                )
            if session_provider_id(record) not in (None, opened_binding.get("provider-id")):
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="provider-open result conflicts with the admitted session provider",
                    details={"session-id": session_id},
                )
            if opened_record.get("execution-profile-id") != record.get("execution-profile-id"):
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="provider-open profile differs from the admitted session profile",
                    details={"session-id": session_id},
                )
            record["binding"] = current_binding or opened_binding
            record["provider-transport-kind"] = "provider-session"
            provider = dict(record.get("provider") or {})
            opened_provider = dict(opened_record.get("provider") or {})
            opened_metadata = dict(opened_provider.pop("metadata", {}) or {})
            provider.update(opened_provider)
            metadata.update(
                {
                    key: value
                    for key, value in opened_metadata.items()
                    if key not in _RECOVERY_CHECKPOINT_KEYS | _LOAD_BUDGET_KEYS
                }
            )
            provider["metadata"] = metadata
            record["provider"] = provider
            record.setdefault("timing", {})["updated-at"] = now_iso_z()
            _validate(record, code="VAL-AGW-120")
            write_session_record(project_root, record)
            try:
                bindings.register_open_binding(project_root, record)
            except Exception:
                # The session record is canonical. Roll back ordinary index
                # failures; a process crash between the two writes leaves a
                # recoverable record and the next idempotent registration
                # repairs the derived index.
                write_session_record(project_root, previous_record)
                previous_binding = previous_record.get("binding")
                if not (
                    isinstance(previous_binding, dict)
                    and previous_binding.get("binding-id")
                    == (record.get("binding") or {}).get("binding-id")
                ):
                    try:
                        bindings.retire_binding(project_root, record, state="failed")
                    except Exception:  # noqa: BLE001 - best-effort derived-index repair
                        logger.exception("failed to retire partial prepared binding registration")
                raise
            if on_commit is not None:
                on_commit(record)
            return record


def release_prepared_submission_recovery_claim(
    project_root: Path, session_id: str, *, claim_id: str
) -> bool:
    """Release a failed opener's claim without consuming the prepared proof."""
    with _ordered_session_mutation_lock(project_root, session_id):
        try:
            record = read_session_record(project_root, session_id)
        except AudiaGenticError:
            return False
        metadata = session_provider_metadata(record)
        claim = metadata.get("submission-recovery-claim")
        if not isinstance(claim, dict) or claim.get("claim-id") != claim_id:
            return False
        metadata.pop("submission-recovery-claim", None)
        record.setdefault("provider", {})["metadata"] = metadata
        record.setdefault("timing", {})["updated-at"] = now_iso_z()
        write_session_record(project_root, record)
        return True


def session_turn_count(record: dict[str, Any]) -> int:
    return (record.get("activity") or {}).get("turn-count") or 0


def session_request_ids(record: dict[str, Any]) -> list[str]:
    return list((record.get("activity") or {}).get("request-ids") or [])


def session_created_at(record: dict[str, Any]) -> str | None:
    return (record.get("timing") or {}).get("created-at")


def session_updated_at(record: dict[str, Any]) -> str | None:
    return (record.get("timing") or {}).get("updated-at")


def session_last_activity_at(record: dict[str, Any]) -> str | None:
    return (record.get("timing") or {}).get("last-activity-at")


def session_closed_at(record: dict[str, Any]) -> str | None:
    return (record.get("timing") or {}).get("closed-at")


def session_idle_timeout_seconds(record: dict[str, Any]) -> float | None:
    return (record.get("policy") or {}).get("idle-timeout-seconds")


def session_max_lifetime_seconds(record: dict[str, Any]) -> float | None:
    return (record.get("policy") or {}).get("max-lifetime-seconds")


def session_created_age_seconds(
    record: dict[str, Any], *, now: datetime | None = None
) -> float | None:
    """Return the durable age of a session, or ``None`` for invalid metadata."""
    created_at = session_created_at(record)
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current.astimezone(timezone.utc) - created.astimezone(timezone.utc)).total_seconds())


def session_lifetime_expiry(record: dict[str, Any]) -> datetime | None:
    """Derive the absolute max-lifetime expiry from durable session fields."""
    age = session_created_age_seconds(record)
    max_lifetime = session_max_lifetime_seconds(record)
    created_at = session_created_at(record)
    if age is None or not isinstance(created_at, str):
        return None
    try:
        cap = float(max_lifetime) if max_lifetime is not None else 0.0
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if cap <= 0:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc) + timedelta(seconds=cap)


def session_lifetime_expired(
    record: dict[str, Any], *, now: datetime | None = None
) -> bool:
    """Return whether the durable absolute max-lifetime has elapsed."""
    expiry = session_lifetime_expiry(record)
    if expiry is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) > expiry


def session_idle_expired(
    record: dict[str, Any], *, now: datetime | None = None
) -> bool:
    """Return whether a durable, non-live session exceeded its idle policy."""
    value = session_idle_timeout_seconds(record)
    if value is None:
        # Legacy GPT-auto records predate persisted policy fields.  Their
        # admission path used gpt_idle_grace's 30-minute default; interpreting
        # the missing value as disabled leaves those records active forever.
        provider_id = session_provider_id(record) or ""
        if provider_id.startswith("gpt-auto"):
            value = 1800.0
    try:
        cap = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return False
    if cap <= 0:
        return False
    timestamp = (record.get("timing") or {}).get("last-activity-at")
    if not isinstance(timestamp, str) or not timestamp.strip():
        return False
    try:
        activity = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if activity.tzinfo is None:
        activity = activity.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current.astimezone(timezone.utc) - activity.astimezone(timezone.utc)).total_seconds() > cap


def expire_session_if_policy_exceeded(
    project_root: Path, session_id: str
) -> dict[str, Any]:
    """Apply durable max-lifetime and idle bounds before reuse or projection."""
    record = read_session_record(project_root, session_id)
    if record.get("state") in SESSION_TERMINAL_STATES:
        return record
    reason = None
    if session_lifetime_expired(record):
        reason = "max-lifetime"
    elif session_idle_expired(record):
        reason = "idle-timeout"
    if reason is None:
        return record
    # Reconciliation acquires request locks before the project retention and
    # session locks. This is the order used by terminal checkpoint cleanup
    # and submission writers; taking retention first here can deadlock against
    # a finalizer holding a request lock while waiting for retention.
    expired = _reconcile_nonterminal_requests_before_expiry(
        project_root, record, reason=reason
    )
    if expired is None:
        return read_session_record(project_root, session_id)
    try:
        record_session_timeline(
            project_root,
            session_id,
            "session.expired",
            state="expired",
            attributes={"close-reason": reason},
        )
    except Exception:  # noqa: BLE001 - expiry state is already authoritative
        logger.warning("failed to record durable session expiry timeline", exc_info=True)
    return expired


def _reconcile_nonterminal_requests_before_expiry(
    project_root: Path,
    session: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any] | None:
    """Retire request records whose provider session has durably expired.

    A previous protection rule refused to expire any session carrying a
    non-terminal request.  That avoided a broken session/request pair, but it
    also left stale non-live sessions and running requests immortal after a
    gateway restart.  Request terminalization is deliberately performed
    before the session transition; if a request fence changes, the session is
    left active for a later safe sweep.

    This is deliberately not a success/capture path.  A visible response may
    belong to another turn or another target; operator/provider reconciliation
    remains responsible for proving and capturing it later.
    """
    from audiagentic.components.agents.gateway import store

    session_id = session.get("session-id")
    if not isinstance(session_id, str) or not session_id:
        return None
    request_ids = set(session_request_ids(session))
    try:
        records = store.list_records(project_root, include_output=False)
    except Exception:  # noqa: BLE001 - expiry state remains authoritative
        logger.warning(
            "could not enumerate requests for expired session",
            extra={"session-id": session_id},
            exc_info=True,
        )
        return None
    request_ids.update(
        str(record.get("request-id"))
        for record in records
        if record.get("session-id") == session_id and record.get("request-id")
    )
    request_snapshots: dict[str, dict[str, Any]] = {}
    for request_id in sorted(request_ids):
        try:
            record = store.read_record(project_root, request_id)
            request_snapshots[request_id] = record
        except Exception:  # noqa: BLE001 - one record must not block expiry
            logger.warning(
                "could not inspect request owned by expiring session",
                extra={"request-id": request_id, "session-id": session_id},
                exc_info=True,
            )
            return None

    nonterminal = [
        record
        for record in request_snapshots.values()
        if record.get("state") not in store.TERMINAL_STATES
    ]

    eligible: list[dict[str, Any]] = []
    if nonterminal:
        session_provider_metadata_value = session_provider_metadata(session)
        session_provider_session_id = session_provider_metadata_value.get("provider-session-id")
        session_provider_id_value = session_provider_id(session)
        binding = session.get("binding")
        binding_provider_id = binding.get("provider-id") if isinstance(binding, dict) else None
        binding_provider_session_ref = binding.get("provider-session-ref") if isinstance(binding, dict) else None
        if (
            not isinstance(session_provider_session_id, str)
            or not session_provider_session_id.strip()
            or not isinstance(session_provider_id_value, str)
            or not session_provider_id_value.strip()
            or binding_provider_id != session_provider_id_value
            or binding_provider_session_ref != session_provider_session_id
        ):
            return None
        for record in nonterminal:
            request_metadata = record.get("provider-metadata")
            if not isinstance(request_metadata, dict):
                return None
            request_provider_session_id = request_metadata.get("provider-session-id")
            if (
                not isinstance(request_provider_session_id, str)
                or not request_provider_session_id.strip()
                or request_provider_session_id != session_provider_session_id
                or record.get("resolved-provider-id") != session_provider_id_value
            ):
                return None
            activity = record.get("activity")
            provider_activity = activity.get("provider") if isinstance(activity, dict) else None
            # The legacy top-level lease is the gateway owner/synthetic lease. It
            # must never keep a provider session alive during expiry reconciliation.
            lease = provider_activity.get("lease-expires-at") if isinstance(provider_activity, dict) else None
            if isinstance(lease, str) and lease.strip():
                try:
                    lease_at = datetime.fromisoformat(lease.replace("Z", "+00:00"))
                    if lease_at.tzinfo is None:
                        lease_at = lease_at.replace(tzinfo=timezone.utc)
                    if lease_at > datetime.now(timezone.utc):
                        return None
                except (TypeError, ValueError):
                    # An invalid lease is not meaningful proof of liveness.
                    pass
            eligible.append(record)

    eligible_ids = {str(record.get("request-id")) for record in eligible}
    with ExitStack() as request_locks:
        # Hold every request mutation lock through the session transition's
        # logical operation. Activity/cancellation writers use these same
        # locks, so request B cannot advance after request A is terminalized.
        # Stable ordering avoids competing multi-request expiry sweeps.
        for request_id in sorted(eligible_ids):
            request_locks.enter_context(_request_lock(project_root, request_id))

        # Global lock order: request(s) -> retention -> session. Revalidate
        # the complete request roster under retention so a newly attached
        # request or changed request revision aborts this expiry attempt.
        with StartupLock(gateway_retention_lock_path(project_root)), _session_lock(
            project_root, session_id
        ):
            current_session = read_session_record(project_root, session_id)
            if current_session.get("state") in SESSION_TERMINAL_STATES:
                return current_session
            reason = None
            if session_lifetime_expired(current_session):
                reason = "max-lifetime"
            elif session_idle_expired(current_session):
                reason = "idle-timeout"
            if reason is None:
                return current_session

            current_ids = set(session_request_ids(current_session))
            try:
                current_records = store.list_records(project_root, include_output=False)
            except Exception:  # noqa: BLE001 - do not expire on incomplete roster
                logger.warning(
                    "could not revalidate requests for expired session",
                    extra={"session-id": session_id},
                    exc_info=True,
                )
                return None
            current_ids.update(
                str(item.get("request-id"))
                for item in current_records
                if item.get("session-id") == session_id and item.get("request-id")
            )
            if current_ids != request_ids:
                return None

            current_by_id = {
                str(item.get("request-id")): item
                for item in current_records
                if item.get("session-id") == session_id and item.get("request-id")
            }
            current_nonterminal_ids = {
                request_id
                for request_id in current_ids
                if request_id in current_by_id
                and current_by_id[request_id].get("state") not in store.TERMINAL_STATES
            }
            if current_nonterminal_ids != eligible_ids:
                return None

            for record in eligible:
                current = store.read_record(project_root, str(record.get("request-id")))
                if (
                    current.get("state") in store.TERMINAL_STATES
                    or current.get("revision") != record.get("revision")
                ):
                    return None

            for record in eligible:
                request_id = str(record.get("request-id"))
                try:
                    side_effect_state = "may-have-started"
                    diagnostics = record.get("diagnostics")
                    if isinstance(diagnostics, dict):
                        side_effect_state = diagnostics.get("side-effect-state") or side_effect_state
                    error = {
                        "code": "CON-AGW-084",
                        "kind": "agents",
                        "message": "provider session expired before the request reached a terminal state",
                        "details": {
                            "session-id": session_id,
                            "session-close-reason": reason,
                            "failure-reason": "provider-session-expired",
                            "side-effect-state": side_effect_state,
                            "watchdog-classification": "expired-provider-session",
                            "reconciliation": "provider-capture-required",
                            "retry-safe": False,
                        },
                    }
                    updated = store.transition_recovered_terminal(
                        project_root,
                        request_id,
                        "interrupted",
                        error=error,
                        stale_epoch=record.get("dispatch-owner-epoch") or None,
                        expected_revision=record.get("revision"),
                        replay_required=False,
                        replay_reason="provider-session-expired; reconcile or operator-capture before retry",
                        _request_lock_held=True,
                    )
                    store.record_gateway_timeline(
                        project_root,
                        request_id,
                        "request.interrupted",
                        state=updated.get("state"),
                        attributes={
                            "source": "session-expiry-reconciliation",
                            "session-id": session_id,
                            "session-close-reason": reason,
                        },
                    )
                except Exception:  # noqa: BLE001 - one record must not block session expiry
                    logger.warning(
                        "could not reconcile request owned by expired session",
                        extra={"request-id": request_id, "session-id": session_id},
                        exc_info=True,
                    )
                    return None
            expired = _transition_session_record_locked(
                project_root,
                session_id,
                current_session,
                "expired",
                updates={"close-reason": reason, "closed-at": now_iso_z()},
            )
            bindings.retire_binding(project_root, expired, state="expired")
            return expired


def expire_session_if_lifetime_exceeded(
    project_root: Path, session_id: str
) -> dict[str, Any]:
    """Persist expiry before recovery can re-open an over-age session."""
    record = read_session_record(project_root, session_id)
    if record.get("state") in SESSION_TERMINAL_STATES or not session_lifetime_expired(record):
        return record
    return expire_session_if_policy_exceeded(project_root, session_id)


def record_session_timeline(
    project_root: Path,
    session_id: str,
    event: str,
    *,
    state: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ..retention import journal_max_bytes

    return record_timeline_event(
        gateway_session_timeline_path(project_root, session_id),
        component=_COMPONENT_ID,
        resource_kind=_RESOURCE_KIND,
        resource_id=session_id,
        event=event,
        state=state,
        attributes=attributes,
        segment_max_bytes=journal_max_bytes("timeline"),
        correlation_id=(attributes or {}).get("correlation_id")
        or (attributes or {}).get("correlation-id"),
    )


def _session_lock(project_root: Path, session_id: str) -> StartupLock:
    """Return the foundation cross-process lock for one session record.

    RV733: session mutation previously used a process-local threading.Lock
    while request records (agents_gateway_store._request_lock) already used
    the foundation StartupLock — a gap for the shared-service architecture
    (SH04+), where multiple worker processes can mutate the same session
    record. Mirrors _request_lock exactly: one lock file beside the record,
    safe across processes as well as threads.
    """
    return StartupLock(gateway_session_path(project_root, session_id).with_name("mutation.lock"))


@contextmanager
def _ordered_session_mutation_lock(project_root: Path, session_id: str):
    """Acquire shared retention state before the per-session mutation lock."""
    with StartupLock(gateway_retention_lock_path(project_root)):
        with _session_lock(project_root, session_id):
            yield


def session_generation_fence(project_root: Path, session_id: str) -> StartupLock:
    """The session generation fence (AS118); see ``gateway_session_generation_lock_path``.

    Held by resume across successor creation and by continuation admission
    until the turn is durably accepted. Take it before any request, retention
    or session mutation lock, and never while holding one of them.
    """
    return StartupLock(gateway_session_generation_lock_path(project_root, session_id))


def _retention_claimed(session_id: str, record: dict[str, Any]) -> AudiaGenticError:
    return AudiaGenticError(
        code="CON-AGW-158", kind="agents",
        message="session is claimed by a retention operation and cannot be resumed or continued",
        details={"session-id": session_id},
    )


def assert_no_retention_claim(project_root: Path, session_id: str) -> dict[str, Any]:
    """Refuse when a retention operation has claimed the session. Call under the generation fence."""
    record = read_session_record(project_root, session_id)
    if record.get("retention-claim") is not None:
        raise _retention_claimed(session_id, record)
    return record


def record_accepted_turn(project_root: Path, session_id: str) -> dict[str, Any]:
    """Stamp ``timing.last-accepted-turn-at`` when a turn is durably admitted.

    The purge inactivity clock (SH32) reads only this field. Call under the
    generation fence; a claimed session is refused rather than revived.
    """
    with _ordered_session_mutation_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        if record.get("retention-claim") is not None:
            raise _retention_claimed(session_id, record)
        updated = dict(record)
        timing = dict(updated.get("timing") or {})
        # Only ever forward: a clock step back must not make a session look older.
        timing["last-accepted-turn-at"] = max(now_iso_z(), timing.get("last-accepted-turn-at") or "")
        timing["updated-at"] = now_iso_z()
        updated["timing"] = timing
        write_session_record(project_root, updated)
        return updated


def claim_retention(project_root: Path, session_id: str, *, operation_id: str) -> dict[str, Any]:
    """Durably claim a terminal session for a retention operation (idempotent per operation).

    Takes the generation fence, so it serializes with resume and continuation
    admission: whichever commits first wins, and the loser rereads. The claim
    outlives the process, unlike the file lock.
    """
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
        raise AudiaGenticError(code="VAL-AGW-052", kind="agents",
                               message="retention claim requires a bounded operation id", details={})
    with session_generation_fence(project_root, session_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            record = read_session_record(project_root, session_id)
            claim = record.get("retention-claim")
            if claim is not None:
                if claim.get("operation-id") == operation_id:
                    return record
                raise _retention_claimed(session_id, record)
            if record.get("state") not in SESSION_TERMINAL_STATES:
                raise AudiaGenticError(
                    code="CON-AGW-159", kind="agents",
                    message="only a terminal session can be claimed for retention",
                    details={"session-id": session_id, "state": record.get("state")},
                )
            updated = dict(record)
            updated["retention-claim"] = {"operation-id": operation_id, "claimed-at": now_iso_z()}
            write_session_record(project_root, updated)
            return updated


def release_retention_claim(project_root: Path, session_id: str, *, operation_id: str) -> dict[str, Any]:
    """Cancel a claim before any destructive work begins; only the claiming operation may.

    A retention operation that goes on to delete keeps its claim until the
    session record itself is removed, so nothing can resume or continue a
    partially deleted lineage.
    """
    with session_generation_fence(project_root, session_id):
        with _ordered_session_mutation_lock(project_root, session_id):
            record = read_session_record(project_root, session_id)
            claim = record.get("retention-claim")
            if claim is None:
                return record
            if claim.get("operation-id") != operation_id:
                raise _retention_claimed(session_id, record)
            updated = dict(record)
            del updated["retention-claim"]
            write_session_record(project_root, updated)
            return updated


def generate_session_id() -> str:
    """Return a new session ID (UUID-based, mirrors generate_request_id)."""
    return f"ses_{uuid.uuid4().hex[:16]}"


def _redact_error(error: BaseException | dict[str, Any] | None) -> dict[str, Any] | None:
    """Reduce any error to a safe {code, message, kind} summary (Standard 8)."""
    if error is None:
        return None
    if isinstance(error, AudiaGenticError):
        return {"code": error.code, "message": error.message, "kind": error.kind}
    if isinstance(error, BaseException):
        # Preserve ordinary validation detail for operator diagnosis; secret
        # material is not expected in ValueError messages and the outer error
        # boundary still redacts provider/authentication exceptions.
        if isinstance(error, ValueError) and str(error):
            return {"code": "VAL-AGW-999", "message": str(error), "kind": type(error).__name__}
        return {
            "code": "UNKNOWN",
            "message": "unexpected error (see server logs)",
            "kind": type(error).__name__,
        }
    return {k: v for k, v in error.items() if k in _REDACTED_ERROR_KEYS}


def build_session_record(
    *,
    session_id: str | None = None,
    created_by_request_id: str | None = None,
    provider_transport_kind: str = "provider-session",
    execution_profile_id: str,
    provider_id: str | None = None,
    model_id: str | None = None,
    provider_session_ref: str | None = None,
    surface_id: str | None = None,
    provider_metadata: dict[str, Any] | None = None,
    idle_timeout_seconds: float | None = None,
    max_lifetime_seconds: float | None = None,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
    context_id: str | None = None,
    agent_definition_id: str | None = None,
    agent_definition_digest: str | None = None,
    role_ids: tuple[str, ...] | list[str] | None = None,
    role_set_digest: str | None = None,
    execution_profile_digest: str | None = None,
    effective_capability_digest: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a new session record in the initial 'active' state."""
    # 0 is a valid value for both bounds: it DISABLES that bound (RV513 —
    # long-lived remote-control sessions need to opt out of the caps).
    if idle_timeout_seconds is not None and idle_timeout_seconds < 0:
        raise AudiaGenticError(
            code="VAL-AGW-050",
            kind="agents",
            message="idle_timeout_seconds must be positive, or 0 to disable the idle timeout",
            details={"idle_timeout_seconds": idle_timeout_seconds},
        )
    if max_lifetime_seconds is not None and max_lifetime_seconds < 0:
        raise AudiaGenticError(
            code="VAL-AGW-051",
            kind="agents",
            message="max_lifetime_seconds must be positive, or 0 to disable the lifetime cap",
            details={"max_lifetime_seconds": max_lifetime_seconds},
        )
    timestamp = now_iso_z()
    created_timestamp = created_at or timestamp
    if provider_transport_kind not in {"worker", "provider-session"}:
        raise ValueError("unknown provider transport kind")
    binding = None
    if provider_session_ref is not None:
        binding = bindings.build_binding(
            provider_id=provider_id,
            provider_session_ref=provider_session_ref,
            surface_id=surface_id,
            identity_context_fingerprint=identity_context_fingerprint,
            execution_context_fingerprint=execution_context_fingerprint,
            context_id=context_id,
            agent_definition_id=agent_definition_id,
            agent_definition_digest=agent_definition_digest,
            role_ids=role_ids,
            role_set_digest=role_set_digest,
            execution_profile_digest=execution_profile_digest,
            effective_capability_digest=effective_capability_digest,
        )
    payload: dict[str, Any] = {
        "contract-version": "v4",
        "session-id": session_id or generate_session_id(),
        "created-by-request-id": created_by_request_id,
        "provider-transport-kind": provider_transport_kind,
        "execution-profile-id": execution_profile_id,
        "binding": binding,
        "state": "active",
        "timing": {
            "created-at": created_timestamp,
            "updated-at": timestamp,
            "last-activity-at": timestamp,
        },
        "activity": {
            "request-ids": [],
            "turn-count": 0,
        },
    }
    provider: dict[str, Any] = {}
    if provider_id is not None:
        provider["provider-id"] = provider_id
    if model_id is not None:
        provider["model-id"] = model_id
    if provider_metadata:
        provider["metadata"] = dict(provider_metadata)
    if provider:
        payload["provider"] = provider
    policy: dict[str, Any] = {}
    if idle_timeout_seconds is not None:
        policy["idle-timeout-seconds"] = idle_timeout_seconds
    if max_lifetime_seconds is not None:
        policy["max-lifetime-seconds"] = max_lifetime_seconds
    if policy:
        payload["policy"] = policy
    return _validate(payload, code="VAL-AGW-052")


def _migrate_v1_record(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("contract-version") != "v1":
        return payload
    migrated = dict(payload)
    provider_session_ref = migrated.pop("provider-session-ref", None)
    migrated["contract-version"] = "v2"
    # Deterministic derivation: re-reading the same v1 file must always yield
    # the same binding identity (binding-id, created-at) — a read is not
    # allowed to mint a new logical identity.
    migrated["binding"] = bindings.build_migrated_v1_binding(
        session_id=str(migrated.get("session-id") or ""),
        provider_id=migrated.get("provider-id"),
        provider_session_ref=provider_session_ref,
        created_at=str(migrated.get("created-at") or ""),
    )
    return migrated


def _migrate_v2_record(payload: dict[str, Any]) -> dict[str, Any]:
    """v2 (flat) -> v3 (grouped provider/timing/policy/activity, omit-if-absent).

    Pure reshaping of an already-valid v2 record: no field is dropped or
    reinterpreted, just regrouped, and absent-valued optional fields (None,
    empty dict/list) are omitted rather than persisted as null/{}/[] --
    v2 always wrote every field; v3's schema only requires the ones that are
    always meaningful.
    """
    if payload.get("contract-version") != "v2":
        return payload
    migrated: dict[str, Any] = {
        "contract-version": "v3",
        "session-id": payload.get("session-id"),
        "execution-profile-id": payload.get("execution-profile-id"),
        "binding": payload.get("binding"),
        "state": payload.get("state"),
        "timing": {
            "created-at": payload.get("created-at"),
            "updated-at": payload.get("updated-at"),
            "last-activity-at": payload.get("last-activity-at") or payload.get("created-at"),
        },
        "activity": {
            "request-ids": list(payload.get("request-ids") or []),
            "turn-count": payload.get("turn-count") or 0,
        },
    }
    if payload.get("closed-at") is not None:
        migrated["timing"]["closed-at"] = payload["closed-at"]
    provider: dict[str, Any] = {}
    if payload.get("provider-id") is not None:
        provider["provider-id"] = payload["provider-id"]
    if payload.get("model-id") is not None:
        provider["model-id"] = payload["model-id"]
    if payload.get("provider-metadata"):
        provider["metadata"] = dict(payload["provider-metadata"])
    if provider:
        migrated["provider"] = provider
    policy: dict[str, Any] = {}
    if payload.get("idle-timeout-seconds") is not None:
        policy["idle-timeout-seconds"] = payload["idle-timeout-seconds"]
    if payload.get("max-lifetime-seconds") is not None:
        policy["max-lifetime-seconds"] = payload["max-lifetime-seconds"]
    if policy:
        migrated["policy"] = policy
    if payload.get("close-reason") is not None:
        migrated["close-reason"] = payload["close-reason"]
    if payload.get("error") is not None:
        migrated["error"] = payload["error"]
    return migrated


def _validate(payload: dict[str, Any], *, code: str) -> dict[str, Any]:
    payload = _migrate_v2_record(_migrate_v1_record(payload))
    issues = validate_with_schema(_SCHEMA_STEM, payload)
    if issues:
        raise AudiaGenticError(
            code=code,
            kind="agents",
            message="gateway session record failed schema validation",
            details={"issues": issues},
        )
    return payload


def write_session_record(project_root: Path, payload: dict[str, Any]) -> Path:
    session_id = payload.get("session-id")
    if not session_id:
        raise AudiaGenticError(
            code="VAL-AGW-053",
            kind="agents",
            message="gateway session record missing session-id",
            details={},
        )
    payload = _validate(payload, code="VAL-AGW-054")
    target = gateway_session_path(project_root, session_id)
    atomic_write_json(target, payload)
    return target


def read_session_record(project_root: Path, session_id: str) -> dict[str, Any]:
    import json

    path = gateway_session_path(project_root, session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AudiaGenticError(
            code="RES-AGW-002",
            kind="agents",
            message="gateway session not found",
            details={"session-id": session_id},
        ) from exc
    except ValueError as exc:
        logger.warning(
            "failed to parse gateway session record",
            extra={"session-id": session_id},
            exc_info=True,
        )
        raise AudiaGenticError(
            code="IO-AGW-002",
            kind="agents",
            message="failed to read gateway session record",
            details={"session-id": session_id},
        ) from exc
    return _validate(payload, code="VAL-AGW-055")


def read_session_record_raw(project_root: Path, session_id: str) -> dict[str, Any] | None:
    """Read a session record's raw JSON payload without schema validation.

    AS33: capability-snapshot/resolved-capabilities/session-capabilities are
    forward-looking fields a future session-surface resolver may write before
    they are formally added to the session schema. A schema-validating read
    would reject the whole record on an unrecognized field, so capability
    projection reads the raw payload directly instead. Returns None (not an
    error) when the session doesn't exist or fails to parse — capability
    projection is best-effort diagnostic sugar, never a hard dependency.
    """
    import json

    path = gateway_session_path(project_root, session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── Binding-specific read/write helpers (AS30 Stage-2) ──────────────


def write_session_binding(
    project_root: Path,
    session_id: str,
    *,
    binding: dict[str, Any],
) -> Path:
    """Atomically write a v2 session record with the given binding object.

    The binding object must carry at least the keys required by the session
    schema (binding-id, provider-id, surface-id, provider-session-ref,
    relation, ownership, created-at). This is the authoritative write path
    for creating a new session with its provider binding — it validates the
    full record shape and writes atomically.

    Raises AudiaGenticError on schema validation failure.
    """
    # Build a minimal v2 session record carrying the binding.
    record = {
        "contract-version": "v2",
        "session-id": session_id,
        "binding": binding,
        "state": "active",
    }
    _validate(record, code="VAL-AGW-100")
    target = gateway_session_path(project_root, session_id)
    atomic_write_json(target, record)
    return target


def read_session_binding(project_root: Path, session_id: str) -> dict[str, Any] | None:
    """Read the binding object for a session.

    Returns the full binding dict (including the opaque provider-session-ref)
    from the persisted v2 record. Returns None when the session does not
    exist or has no binding.

    On a v1 record, migrates in memory and returns the deterministically
    derived binding — never writes back unless explicitly requested.
    """
    try:
        record = read_session_record(project_root, session_id)
    except AudiaGenticError:
        return None
    binding = record.get("binding")
    if not isinstance(binding, dict):
        return None
    return binding


def install_initial_provider_binding(
    project_root: Path,
    session_id: str,
    *,
    provider_id: str,
    surface_id: str,
    provider_session_ref: str,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
    context_id: str | None = None,
    agent_definition_id: str | None = None,
    agent_definition_digest: str | None = None,
    role_ids: tuple[str, ...] | list[str] | None = None,
    role_set_digest: str | None = None,
    execution_profile_digest: str | None = None,
    effective_capability_digest: str | None = None,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> dict[str, Any]:
    """Install a session's first provider-native binding exactly once.

    Repeating the same reference is idempotent and may refresh bounded scalar
    provider metadata. A different reference is a generation conflict and is
    never written in place.
    """
    with _ordered_session_mutation_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        admitted_provider = session_provider_id(record)
        if admitted_provider and admitted_provider != provider_id:
            raise AudiaGenticError(
                code="CON-AGW-120",
                kind="agents",
                message="provider binding does not match the admitted session provider",
                details={"session-id": session_id, "provider-id": provider_id},
            )
        current = record.get("binding")
        if isinstance(current, dict):
            if (
                current.get("provider-session-ref") != provider_session_ref
                or current.get("provider-id") != provider_id
                or current.get("surface-id") != surface_id
            ):
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="provider session binding is immutable within a session generation",
                    details={"session-id": session_id},
                )
        else:
            provider = record.get("provider")
            if not isinstance(provider, dict):
                provider = {}
                record["provider"] = provider
            current = bindings.build_binding(
                provider_id=provider_id,
                provider_session_ref=provider_session_ref,
                surface_id=surface_id,
                identity_context_fingerprint=identity_context_fingerprint,
                execution_context_fingerprint=execution_context_fingerprint,
                context_id=context_id,
                agent_definition_id=agent_definition_id,
                agent_definition_digest=agent_definition_digest,
                role_ids=role_ids,
                role_set_digest=role_set_digest,
                execution_profile_digest=execution_profile_digest,
                effective_capability_digest=effective_capability_digest,
            )
            record["binding"] = current

        if metadata:
            provider = record.setdefault("provider", {})
            existing = provider.setdefault("metadata", {})
            # Provider binding updates are not request-owned checkpoint
            # writes. In particular, GPT-auto may publish message identity
            # before its first prepared checkpoint; allowing unresolved-turn
            # scalars through here creates a pending fence with no owner,
            # turn id, or submission stage and makes the prepared CAS fail.
            # Recovery fields have their own owner-fenced mutation path below.
            existing.update(
                {
                    key: value
                    for key, value in metadata.items()
                    if key not in _RECOVERY_CHECKPOINT_KEYS | _LOAD_BUDGET_KEYS
                }
            )
        record.setdefault("timing", {})["updated-at"] = now_iso_z()
        _validate(record, code="VAL-AGW-120")
        # Register first so a retry repairs either side of a partial caller
        # failure without ever permitting a conflicting provider reference.
        bindings.register_open_binding(project_root, record)
        atomic_write_json(gateway_session_path(project_root, session_id), record)
        return record


def list_session_records(project_root: Path) -> list[dict[str, Any]]:
    root = gateway_sessions_root(project_root)
    if not root.exists():
        return []
    records = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            records.append(read_session_record(project_root, entry.name))
        except AudiaGenticError:
            logger.warning(
                "skipping unreadable gateway session",
                extra={"session-id": entry.name},
                exc_info=True,
            )
    return records


def latest_turn_quality_summary(
    project_root: Path,
    session_id: str,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Return bounded scalar quality-summary fields for AS36 terminal classification.

    Reads only the persisted session timeline and extracts sequence/kind/time
    fields needed by agents_terminal_quality.classify_terminal_output().
    No text, provider refs, tool names, args, outputs, or raw payloads are
    returned — only bounded scalar facts (AS36 step 4).
    """
    try:
        entries = iter_ndjson(gateway_session_timeline_path(project_root, session_id))
    except (OSError, ValueError):
        logger.warning(
            "failed to read gateway session timeline for quality summary",
            extra={"session-id": session_id},
        )
        return None

    event_count = 0
    last_event_kind: str | None = None
    last_event_sequence: int | None = None
    last_event_at: str | None = None
    last_assistant_event_sequence: int | None = None
    last_tool_event_sequence: int | None = None
    result_sequence: int | None = None
    stop_reason: str | None = None

    for entry in entries:
        event_name = entry.get("event")
        if not isinstance(event_name, str) or not event_name.startswith("session.turn."):
            continue
        attrs = entry.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}
        # Filter by request-id if specified
        entry_request_id = attrs.get("request-id")
        if request_id is not None and entry_request_id != request_id:
            continue
        # Only scalar fields — bounded discipline
        kind = attrs.get("kind")
        if not isinstance(kind, str):
            kind = event_name.split(".")[-1] if "." in event_name else None
        sequence = attrs.get("sequence")
        if not isinstance(sequence, int):
            try:
                sequence = int(sequence) if sequence is not None else None
            except (TypeError, ValueError):
                sequence = None
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, str):
            timestamp = None

        event_count += 1
        last_event_kind = kind
        last_event_sequence = sequence
        last_event_at = timestamp

        if kind == "assistant-message" or kind == "thought":
            if sequence is not None and (
                last_assistant_event_sequence is None or sequence > last_assistant_event_sequence
            ):
                last_assistant_event_sequence = sequence
        elif kind == "tool-call":
            if sequence is not None and (
                last_tool_event_sequence is None or sequence > last_tool_event_sequence
            ):
                last_tool_event_sequence = sequence
        elif kind == "result":
            if sequence is not None:
                result_sequence = sequence

        # Capture stop-reason if present (scalar only)
        sr = attrs.get("stop-reason")
        if isinstance(sr, str):
            stop_reason = sr

    if event_count == 0:
        return None

    return {
        "event-count": event_count,
        "last-event-kind": last_event_kind,
        "last-event-sequence": last_event_sequence,
        "last-event-at": last_event_at,
        "last-assistant-event-sequence": last_assistant_event_sequence,
        "last-tool-event-sequence": last_tool_event_sequence,
        "result-sequence": result_sequence,
        "stop-reason": stop_reason,
    }


def latest_turn_projection(
    project_root: Path, session_id: str, request_id: str | None = None
) -> dict[str, Any] | None:
    """Return the latest redacted session-turn timeline fact for status.

    Session timelines carry only coarse normalized turn facts here. Keep this
    projection intentionally narrow: no prompt text, output text, tool payloads,
    native frames, or binding internals.
    """
    try:
        entries = iter_ndjson(gateway_session_timeline_path(project_root, session_id))
    except (OSError, ValueError):
        logger.warning("failed to read gateway session timeline", extra={"session-id": session_id})
        return None
    latest: dict[str, Any] | None = None
    for entry in entries:
        event = entry.get("event")
        if not isinstance(event, str) or not event.startswith("session.turn."):
            continue
        attrs = entry.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}
        entry_request_id = attrs.get("request-id")
        if request_id is not None and entry_request_id != request_id:
            continue
        timestamp = entry.get("timestamp")
        state = entry.get("state")
        projected: dict[str, Any] = {
            "event": event,
            "state": state if isinstance(state, str) else None,
            "timestamp": timestamp if isinstance(timestamp, str) else None,
        }
        for key in (
            "request-id",
            "kind",
            "sequence",
            "semantic-strength",
            "verification-tier",
            "stop-reason",
            "turn-count",
        ):
            value = attrs.get(key)
            if isinstance(value, (str, int, float, bool)):
                projected[key] = value
        latest = projected
    return latest


def build_session_progress_summary(
    project_root: Path,
    session_id: str,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Build a richer bounded progress-summary from the session timeline (SH15).

    Reads the persisted NDJSON timeline and computes:
      - latest sequence / timestamp
      - event-kind counts (thought, assistant-message, tool-call, result, …)
      - active / completed / failed tool counts (from tool-call events with status)
      - assistant/thought chunk count + total byte size
      - terminal stop_reason
      - dropped-events / total-events counters (from turn.finished records)
      - callback-disabled health flag (from turn.finished records)

    Returns None when no session timeline exists or it is unreadable.
    Only scalar fields — no text, provider refs, tool args, or raw payloads.
    """
    try:
        entries = iter_ndjson(gateway_session_timeline_path(project_root, session_id))
    except (OSError, ValueError):
        logger.warning(
            "failed to read gateway session timeline for progress summary",
            extra={"session-id": session_id},
        )
        return None

    event_kind_counts: dict[str, int] = {}
    # Tool status tracking: each tool-call-id maps to its latest status
    tool_status_map: dict[str, str | None] = {}
    assistant_thought_count = 0
    assistant_thought_bytes = 0
    last_sequence: int | None = None
    last_timestamp: str | None = None
    stop_reason: str | None = None
    dropped_events: int | None = None
    total_events: int | None = None
    callback_disabled: bool | None = None

    for entry in entries:
        event_name = entry.get("event")
        if not isinstance(event_name, str) or not event_name.startswith("session.turn."):
            continue
        attrs = entry.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}
        # Filter by request-id if specified
        entry_request_id = attrs.get("request-id")
        if request_id is not None and entry_request_id != request_id:
            continue

        kind = attrs.get("kind")
        if not isinstance(kind, str):
            kind = event_name.split(".")[-1] if "." in event_name else None

        sequence = attrs.get("sequence")
        if not isinstance(sequence, int):
            try:
                sequence = int(sequence) if sequence is not None else None
            except (TypeError, ValueError):
                sequence = None

        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, str):
            timestamp = None

        # Update latest sequence/timestamp
        if sequence is not None and (last_sequence is None or sequence > last_sequence):
            last_sequence = sequence
            last_timestamp = timestamp

        # Event-kind counts
        if kind is not None:
            event_kind_counts[kind] = event_kind_counts.get(kind, 0) + 1

        # Assistant/thought chunk tracking
        if kind in ("assistant-message", "thought"):
            assistant_thought_count += 1
            # Byte size: approximate from the entry string length
            assistant_thought_bytes += len(str(entry).encode("utf-8"))

        # Tool status tracking (for active/completed/failed counts)
        if kind == "tool-call":
            tool_call_id = attrs.get("tool-call-id")
            status = attrs.get("status")
            if tool_call_id and status:
                tool_status_map[tool_call_id] = str(status)

        # Stop reason from turn.finished entries
        sr = attrs.get("stop-reason")
        if isinstance(sr, str):
            stop_reason = sr

        # Dropped events / total events from turn.finished entries
        de = attrs.get("dropped-events")
        if isinstance(de, int):
            dropped_events = de
        te = attrs.get("total-events")
        if isinstance(te, int):
            total_events = te

        # Callback health from turn.finished entries
        cd = attrs.get("callback-disabled")
        if isinstance(cd, bool):
            callback_disabled = cd

    if last_sequence is None and not event_kind_counts:
        return None

    # Derive tool counts from status map
    active_tools = 0
    completed_tools = 0
    failed_tools = 0
    for tid, status in tool_status_map.items():
        if status in ("completed",):
            completed_tools += 1
        elif status == "failed":
            failed_tools += 1
        else:
            active_tools += 1  # pending, in_progress, or unknown

    return {
        "latest-sequence": last_sequence,
        "latest-timestamp": last_timestamp,
        "event-kind-counts": event_kind_counts if event_kind_counts else None,
        "tool-count-active": active_tools,
        "tool-count-completed": completed_tools,
        "tool-count-failed": failed_tools,
        "assistant-thought-chunk-count": assistant_thought_count,
        "assistant-thought-approx-bytes": assistant_thought_bytes,
        "stop-reason": stop_reason,
        "dropped-events": dropped_events,
        "total-events": total_events,
        "callback-disabled": callback_disabled,
    }


def ensure_session_transition(current_state: str, new_state: str) -> None:
    if not is_known_state(_WORKFLOW, current_state):
        raise AudiaGenticError(
            code="VAL-AGW-056",
            kind="agents",
            message="unknown gateway session state",
            details={"state": current_state},
        )
    if not transition_allowed(_WORKFLOW, current_state, new_state):
        raise AudiaGenticError(
            code="CON-AGW-002",
            kind="agents",
            message="illegal gateway session state transition",
            details={"from": current_state, "to": new_state},
        )


def transition_session_record(
    project_root: Path,
    session_id: str,
    new_state: str,
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transition a session record to a new state and persist it.

    ``updates`` may set mutable lifecycle fields only (close-reason,
    closed-at, last-activity-at, error). Identity fields — session-id,
    execution-profile-id, provider-id, model-id, binding, created-at,
    contract-version — are immutable after creation: one generation has one
    binding; resume/replacement creates a new linked record (AS30), never a
    mutation of this one. ``error`` is redacted before persisting.
    """
    illegal = {key.replace("_", "-") for key in (updates or {})} - _MUTABLE_TRANSITION_FIELDS
    if illegal:
        raise AudiaGenticError(
            code="VAL-AGW-097",
            kind="agents",
            message="session transition may not modify immutable session identity fields",
            details={"session-id": session_id, "rejected-fields": sorted(illegal)},
        )
    with _session_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        return _transition_session_record_locked(
            project_root, session_id, record, new_state, updates=updates
        )


def _transition_session_record_locked(
    project_root: Path,
    session_id: str,
    record: dict[str, Any],
    new_state: str,
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a session transition while the caller holds the session lock."""
    ensure_session_transition(record["state"], new_state)
    updated = dict(record)
    updated["state"] = new_state
    timing = dict(updated.get("timing") or {})
    timing["updated-at"] = now_iso_z()
    for key, value in (updates or {}).items():
        key = key.replace("_", "-")
        if key in ("closed-at", "last-activity-at"):
            if value is None:
                timing.pop(key, None)
            else:
                timing[key] = value
        elif key == "close-reason":
            if value is None:
                updated.pop("close-reason", None)
            else:
                updated["close-reason"] = value
        elif key == "error":
            redacted = _redact_error(value)
            if redacted is None:
                updated.pop("error", None)
            else:
                updated["error"] = redacted
    updated["timing"] = timing
    write_session_record(project_root, updated)
    record_session_timeline(
        project_root,
        session_id,
        "state.changed",
        state=new_state,
        attributes={
            "from": record["state"],
            "to": new_state,
            "close-reason": updated.get("close-reason"),
            "updated-keys": sorted((updates or {}).keys()),
        },
    )
    return updated


def record_session_turn(
    project_root: Path,
    session_id: str,
    request_id: str,
    provider_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a served request and bump turn-count/last-activity.

    Idempotent: replaying finalization for a request-id already recorded
    returns the existing record unchanged — no second count increment, no
    duplicate timeline fact (duplicate/late terminal evidence must not
    create terminal side effects twice).
    """
    with _session_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        activity = dict(record.get("activity") or {})
        request_ids = list(activity.get("request-ids") or [])
        if request_id in request_ids:
            if provider_metadata is None:
                return record
            updated = dict(record)
            provider = dict(updated.get("provider") or {})
            existing_metadata = dict(provider.get("metadata") or {})
            current_metadata = dict(existing_metadata)
            terminal_checkpoint_proven = _terminal_checkpoint_clear_is_proven(
                existing_metadata, provider_metadata, request_id
            )
            checkpoint_keys = _RECOVERY_CHECKPOINT_KEYS | _LOAD_BUDGET_KEYS
            current_metadata.update(
                {
                    key: value
                    for key, value in provider_metadata.items()
                    if key not in checkpoint_keys
                }
            )
            if terminal_checkpoint_proven:
                # Persist the validated terminal witness, but keep the
                # unresolved fence until the request's terminal state and
                # response artifact are durable. The queue owner performs the
                # compare-and-clear afterward under the request + session
                # locks; a crash here must remain recoverable.
                current_metadata["terminal-evidence"] = copy.deepcopy(
                    provider_metadata["terminal-evidence"]
                )
            provider["metadata"] = current_metadata
            updated["provider"] = provider
            timing = dict(updated.get("timing") or {})
            timing["updated-at"] = now_iso_z()
            updated["timing"] = timing
            write_session_record(project_root, updated)
            return updated
        updated = dict(record)
        request_ids.append(request_id)
        activity["request-ids"] = request_ids
        try:
            activity["turn-count"] = int(activity.get("turn-count") or 0) + 1
        except (TypeError, ValueError):
            logger.warning(
                "invalid turn-count in session record; resetting",
                extra={"session-id": session_id},
                exc_info=True,
            )
            activity["turn-count"] = 1
        updated["activity"] = activity
        timestamp = now_iso_z()
        if provider_metadata is not None:
            provider = dict(updated.get("provider") or {})
            existing_metadata = dict(provider.get("metadata") or {})
            current_metadata = dict(existing_metadata)
            terminal_checkpoint_proven = _terminal_checkpoint_clear_is_proven(
                existing_metadata, provider_metadata, request_id
            )
            checkpoint_keys = _RECOVERY_CHECKPOINT_KEYS | _LOAD_BUDGET_KEYS
            current_metadata.update(
                {
                    key: value
                    for key, value in provider_metadata.items()
                    if key not in checkpoint_keys
                }
            )
            if terminal_checkpoint_proven:
                # Do not clear here: request completion/artifact persistence
                # is a separate durable write owned by the queue. Retain the
                # exact checkpoint through that crash window and let the
                # terminal request CAS remove it afterward.
                current_metadata["terminal-evidence"] = copy.deepcopy(
                    provider_metadata["terminal-evidence"]
                )
            provider["metadata"] = current_metadata
            updated["provider"] = provider
        timing = dict(updated.get("timing") or {})
        timing["last-activity-at"] = timestamp
        timing["updated-at"] = timestamp
        updated["timing"] = timing
        write_session_record(project_root, updated)
        record_session_timeline(
            project_root,
            session_id,
            "session.turn.recorded",
            state=updated["state"],
            attributes={"request-id": request_id, "turn-count": activity["turn-count"]},
        )
        return updated
