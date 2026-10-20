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

import logging
import copy
import uuid
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_retention_lock_path,
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
_RECOVERY_CHECKPOINT_KEYS = frozenset(
    {
        "unresolved-turn-pending",
        "unresolved-turn-id",
        "submission-state",
        "submission-proven",
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
    }
)
_RECOVERY_IDENTITY_KEYS = frozenset(
    {
        "unresolved-turn-id",
        "unresolved-baseline-user-id",
        "unresolved-baseline-assistant-id",
        "unresolved-baseline-user-count",
        "unresolved-baseline-assistant-count",
        "prompt-text-digest",
    }
)


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


def clear_terminal_submission_checkpoint(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    recovery_state: str,
    remove_keys: tuple[str, ...],
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
        )


def _clear_terminal_submission_checkpoint_locked(
    project_root: Path,
    session_id: str,
    request_id: str,
    *,
    recovery_state: str,
    remove_keys: tuple[str, ...],
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
    with _ordered_session_mutation_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        metadata = session_provider_metadata(record)
        current_turn_id = metadata.get("unresolved-turn-id")
        if current_turn_id != request_id:
            return False
        metadata["unresolved-turn-pending"] = False
        metadata["recovery-state"] = recovery_state
        for key in remove_keys:
            metadata.pop(key, None)
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
) -> None:
    from audiagentic.components.agents.gateway import store as gateway_store

    request = gateway_store.read_record(project_root, request_id)
    if not (
        request.get("state") == "running"
        and request.get("session-id") == session_id
        and request.get("dispatch-owner-epoch") == dispatch_owner_epoch
        and request.get("worker-id") == worker_id
        and request.get("attempt-epoch") == attempt_epoch
    ):
        raise AudiaGenticError(
            code="CON-AGW-125",
            kind="agents",
            message="prepared submission recovery lost its request owner fence",
            details={"request-id": request_id, "session-id": session_id},
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
            fresh_prepared_checkpoint = (
                current_stage is None
                and metadata.get("unresolved-turn-pending") is not True
                and not _RECOVERY_IDENTITY_KEYS.intersection(metadata)
                and not {
                    "submission-proven",
                    "submission-recovery-claim",
                    "submission-recovery-generation",
                    "terminal-evidence",
                }.intersection(metadata)
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
            if fresh_prepared_checkpoint:
                # The first turn on a newly admitted session has no prior
                # checkpoint (and therefore no recovery claim). The durable
                # request owner is the authority for this one-way initialization.
                _assert_request_dispatch_owner(
                    project_root,
                    request_id,
                    session_id,
                    dispatch_owner_epoch=dispatch_owner_epoch,
                    worker_id=worker_id,
                    attempt_epoch=attempt_epoch,
                )
                if _RECOVERY_CHECKPOINT_KEYS.intersection(remove_keys):
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="initial prepared checkpoint cannot remove recovery evidence",
                        details={"request-id": request_id, "session-id": session_id},
                    )
            elif fresh_prepared_dispatch:
                # The normal first-turn dispatch advances its just-written
                # prepared checkpoint without a recovery claim. Claims are
                # mandatory for a recovered prepared checkpoint; their durable
                # generation distinguishes that case from fresh dispatch.
                _assert_request_dispatch_owner(
                    project_root,
                    request_id,
                    session_id,
                    dispatch_owner_epoch=dispatch_owner_epoch,
                    worker_id=worker_id,
                    attempt_epoch=attempt_epoch,
                )
                if (
                    metadata.get("submission-recovery-claim") is not None
                    or metadata.get("submission-recovery-generation") is not None
                    or metadata.get("unresolved-turn-pending") is not True
                    or metadata.get("unresolved-turn-id") != request_id
                    or metadata.get("submission-proven") is not False
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
                _assert_request_dispatch_owner(
                    project_root,
                    request_id,
                    session_id,
                    dispatch_owner_epoch=dispatch_owner_epoch,
                    worker_id=worker_id,
                    attempt_epoch=attempt_epoch,
                )
                if not (
                    metadata.get("unresolved-turn-pending") is True
                    and metadata.get("unresolved-turn-id") == request_id
                    and current_stage in {None, "dispatching"}
                    and claim_id is None
                ):
                    raise AudiaGenticError(
                        code="CON-AGW-125",
                        kind="agents",
                        message="owned checkpoint update does not match the current dispatch stage",
                        details={"request-id": request_id, "session-id": session_id},
                    )
            if "submission-state" in metadata_update and (
                metadata_update["submission-state"] != "dispatching"
                or metadata.get("submission-state")
                not in {None, "dispatching"}
            ) and not fresh_prepared_checkpoint and not fresh_prepared_dispatch:
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
            if metadata.get("submission-state") == "prepared" and protected_removals:
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="prepared recovery evidence cannot be removed before dispatch",
                    details={"request-id": request_id, "session-id": session_id},
                )
            if protected_removals:
                raise AudiaGenticError(
                    code="CON-AGW-125",
                    kind="agents",
                    message="recovery evidence removal requires a terminal request",
                    details={"request-id": request_id, "session-id": session_id},
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
                        if key not in _RECOVERY_CHECKPOINT_KEYS
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
                    if key not in _RECOVERY_CHECKPOINT_KEYS
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
    # Serialize the request preflight, request terminalization, and session
    # retirement under the same project retention fence.  Per-request CAS is
    # still required, but without this logical-operation lock another writer
    # could change a later request between the all-request preflight and the
    # session transition, leaving a partially reconciled session.
    with StartupLock(gateway_retention_lock_path(project_root)):
        current = read_session_record(project_root, session_id)
        if current.get("state") in SESSION_TERMINAL_STATES:
            return current
        # The session may have been refreshed while this sweep waited for the
        # project fence. Re-evaluate policy from the locked record.
        reason = None
        if session_lifetime_expired(current):
            reason = "max-lifetime"
        elif session_idle_expired(current):
            reason = "idle-timeout"
        if reason is None:
            return current
        expired = _reconcile_nonterminal_requests_before_expiry(project_root, current, reason=reason)
        if expired is None:
            return current
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
    nonterminal: list[dict[str, Any]] = []
    for request_id in sorted(request_ids):
        try:
            record = store.read_record(project_root, request_id)
            if record.get("state") not in store.TERMINAL_STATES:
                nonterminal.append(record)
        except Exception:  # noqa: BLE001 - one record must not block expiry
            logger.warning(
                "could not inspect request owned by expiring session",
                extra={"request-id": request_id, "session-id": session_id},
                exc_info=True,
            )
            return None

    if not nonterminal:
        # No request mutation or provider ownership proof is needed for an
        # empty stale session. Retire it under the caller's retention fence.
        expired = transition_session_record(
            project_root,
            session_id,
            "expired",
            updates={"close-reason": reason, "closed-at": now_iso_z()},
        )
        bindings.retire_binding(project_root, expired, state="expired")
        return expired

    eligible: list[dict[str, Any]] = []
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
        # The legacy top-level lease is the gateway owner/synthetic lease.  It
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

    with ExitStack() as request_locks:
        # Hold every request mutation lock through the session transition's
        # logical operation. Activity/cancellation writers use these same
        # locks, so request B cannot advance after request A is terminalized.
        for record in eligible:
            request_locks.enter_context(_request_lock(project_root, str(record.get("request-id"))))

        # Hold the session mutation fence before the final policy check and
        # keep it through request terminalization and session transition.
        # Activity refreshes use this same lock, so a refresh cannot land
        # between the policy check and expiry.
        with _session_lock(project_root, session_id):
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
    return record_timeline_event(
        gateway_session_timeline_path(project_root, session_id),
        component=_COMPONENT_ID,
        resource_kind=_RESOURCE_KIND,
        resource_id=session_id,
        event=event,
        state=state,
        attributes=attributes,
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
            existing.update(metadata)
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
            current_metadata = dict(provider.get("metadata") or {})
            current_metadata.update(provider_metadata)
            if (
                current_metadata.get("unresolved-turn-pending") is True
                and isinstance(current_metadata.get("terminal-evidence"), dict)
            ):
                current_metadata["unresolved-turn-pending"] = False
                for key in (
                    "recovery-state",
                    "submission-state",
                    "unresolved-turn-id",
                    "unresolved-baseline-user-id",
                    "unresolved-baseline-assistant-id",
                    "unresolved-baseline-user-count",
                    "unresolved-baseline-assistant-count",
                    "unresolved-baseline-error-alert-occurrences",
                    "terminal-evidence",
                ):
                    current_metadata.pop(key, None)
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
            current_metadata = dict(provider.get("metadata") or {})
            current_metadata.update(provider_metadata)
            # The provider result is assembled from the turn's checkpoint
            # snapshot.  A successful turn may therefore still carry the
            # pre-send unresolved marker even though terminal proof already
            # cleared it through the checkpoint sink.  Terminal evidence is
            # the authoritative proof here; do not resurrect a stale fence
            # while recording the completed turn.
            if (
                current_metadata.get("unresolved-turn-pending") is True
                and isinstance(current_metadata.get("terminal-evidence"), dict)
            ):
                current_metadata["unresolved-turn-pending"] = False
                for key in (
                    "recovery-state",
                    "submission-state",
                    "unresolved-turn-id",
                    "unresolved-baseline-user-id",
                    "unresolved-baseline-assistant-id",
                    "unresolved-baseline-user-count",
                    "unresolved-baseline-assistant-count",
                    "unresolved-baseline-error-alert-occurrences",
                    "terminal-evidence",
                ):
                    current_metadata.pop(key, None)
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
