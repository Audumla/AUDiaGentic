"""Agent LLM Gateway session record store (plan agent-sessions AS03).

Durable, observable state for live agent sessions. Live transport handles are
in-memory only (agents_gateway_sessions.SessionRuntime); these records are the
audit trail and the resume anchor (provider-session-ref) for later build-out
(AS10 resume, AS09 remote channeling). Follows agents_gateway_store conventions
exactly: atomic JSON records, schema validation, workflow-driven transitions,
NDJSON timeline, per-record locks.

No prompt or output content is ever persisted here — content lives on request
records, which carry the redaction discipline (Standard 8). Session records
hold lifecycle metadata only.
"""
from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_session_path,
    gateway_session_timeline_path,
    gateway_sessions_root,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.observability import record_timeline_event
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    states_in_set,
    transition_allowed,
)

logger = logging.getLogger(__name__)

_SCHEMA_STEM = "agent-llm-session"
_WORKFLOW = load_workflow(Path(__file__).with_name("workflows.yaml"), "gateway-session")
SESSION_TERMINAL_STATES: set[str] = set(states_in_set(_WORKFLOW, "terminal"))

_REDACTED_ERROR_KEYS = {"code", "message", "kind"}

_session_locks: dict[str, threading.Lock] = {}
_session_locks_guard = threading.Lock()

_COMPONENT_ID = "agents"
_RESOURCE_KIND = "agent-llm-gateway-session"


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
        correlation_id=(attributes or {}).get("correlation_id") or (attributes or {}).get("correlation-id"),
    )


def _session_lock(session_id: str) -> threading.Lock:
    """Per-session lock guarding read-modify-write mutations (mirrors
    agents_gateway_store._request_lock, same RV31 lost-update rationale)."""
    with _session_locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_locks[session_id] = lock
        return lock


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
        return {"code": "UNKNOWN", "message": "unexpected error (see server logs)", "kind": type(error).__name__}
    return {k: v for k, v in error.items() if k in _REDACTED_ERROR_KEYS}


def build_session_record(
    *,
    session_id: str | None = None,
    agent_profile_id: str,
    provider_id: str | None = None,
    model_id: str | None = None,
    provider_session_ref: str | None = None,
    idle_timeout_seconds: float | None = None,
    max_lifetime_seconds: float | None = None,
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
    payload: dict[str, Any] = {
        "contract-version": "v1",
        "session-id": session_id or generate_session_id(),
        "agent-profile-id": agent_profile_id,
        "provider-id": provider_id,
        "model-id": model_id,
        "provider-session-ref": provider_session_ref,
        "state": "active",
        "close-reason": None,
        "idle-timeout-seconds": idle_timeout_seconds,
        "max-lifetime-seconds": max_lifetime_seconds,
        "request-ids": [],
        "turn-count": 0,
        "error": None,
        "created-at": timestamp,
        "updated-at": timestamp,
        "last-activity-at": timestamp,
        "closed-at": None,
    }
    return _validate(payload, code="VAL-AGW-052")


def _validate(payload: dict[str, Any], *, code: str) -> dict[str, Any]:
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
    _validate(payload, code="VAL-AGW-054")
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
        logger.warning("failed to parse gateway session record", extra={"session-id": session_id}, exc_info=True)
        raise AudiaGenticError(
            code="IO-AGW-002",
            kind="agents",
            message="failed to read gateway session record",
            details={"session-id": session_id},
        ) from exc
    return _validate(payload, code="VAL-AGW-055")


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
            logger.warning("skipping unreadable gateway session", extra={"session-id": entry.name}, exc_info=True)
    return records


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

    ``updates`` may set mutable fields (provider-id, model-id,
    provider-session-ref, close-reason, closed-at, last-activity-at, error).
    ``error`` is redacted before persisting.
    """
    with _session_lock(session_id):
        record = read_session_record(project_root, session_id)
        ensure_session_transition(record["state"], new_state)
        updated = dict(record)
        updated["state"] = new_state
        updated["updated-at"] = now_iso_z()
        if updates:
            for key, value in updates.items():
                updated[key.replace("_", "-")] = _redact_error(value) if key in ("error",) else value
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
) -> dict[str, Any]:
    """Append a served request and bump turn-count/last-activity."""
    with _session_lock(session_id):
        record = read_session_record(project_root, session_id)
        updated = dict(record)
        request_ids = list(record.get("request-ids") or [])
        if request_id not in request_ids:
            request_ids.append(request_id)
        updated["request-ids"] = request_ids
        updated["turn-count"] = int(record.get("turn-count") or 0) + 1
        timestamp = now_iso_z()
        updated["last-activity-at"] = timestamp
        updated["updated-at"] = timestamp
        write_session_record(project_root, updated)
        record_session_timeline(
            project_root,
            session_id,
            "session.turn.recorded",
            state=updated["state"],
            attributes={"request-id": request_id, "turn-count": updated["turn-count"]},
        )
        return updated
