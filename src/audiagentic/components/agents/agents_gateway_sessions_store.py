"""Agent LLM Gateway session record store (plan agent-sessions AS03/AS30).

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
import uuid
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_session_bindings as bindings
from audiagentic.components.agents.agents_paths import (
    gateway_session_path,
    gateway_session_timeline_path,
    gateway_sessions_root,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json, load_ndjson
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

_SCHEMA_STEM = "agent-llm-session"
_WORKFLOW = load_workflow(Path(__file__).with_name("workflows.yaml"), "gateway-session")
SESSION_TERMINAL_STATES: set[str] = set(states_in_set(_WORKFLOW, "terminal"))

_REDACTED_ERROR_KEYS = {"code", "message", "kind"}

# Lifecycle fields a workflow transition may update. Everything else on the
# record is identity, immutable after creation (AS30 generation model).
_MUTABLE_TRANSITION_FIELDS = {"close-reason", "closed-at", "last-activity-at", "error"}

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
    binding = bindings.build_binding(
        provider_id=provider_id,
        provider_session_ref=provider_session_ref,
    )
    payload: dict[str, Any] = {
        "contract-version": "v2",
        "session-id": session_id or generate_session_id(),
        "agent-profile-id": agent_profile_id,
        "provider-id": provider_id,
        "model-id": model_id,
        "binding": binding,
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


def _validate(payload: dict[str, Any], *, code: str) -> dict[str, Any]:
    payload = _migrate_v1_record(payload)
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
    payload = _migrate_v1_record(payload)
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
        entries = load_ndjson(gateway_session_timeline_path(project_root, session_id))
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


def latest_turn_projection(project_root: Path, session_id: str, request_id: str | None = None) -> dict[str, Any] | None:
    """Return the latest redacted session-turn timeline fact for status.

    Session timelines carry only coarse normalized turn facts here. Keep this
    projection intentionally narrow: no prompt text, output text, tool payloads,
    native frames, or binding internals.
    """
    try:
        entries = load_ndjson(gateway_session_timeline_path(project_root, session_id))
    except (OSError, ValueError):
        logger.warning("failed to read gateway session timeline", extra={"session-id": session_id})
        return None
    for entry in reversed(entries):
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
        return projected
    return None


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
        entries = load_ndjson(gateway_session_timeline_path(project_root, session_id))
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
    agent-profile-id, provider-id, model-id, binding, created-at,
    contract-version — are immutable after creation: one generation has one
    binding; resume/replacement creates a new linked record (AS30), never a
    mutation of this one. ``error`` is redacted before persisting.
    """
    illegal = {
        key.replace("_", "-") for key in (updates or {})
    } - _MUTABLE_TRANSITION_FIELDS
    if illegal:
        raise AudiaGenticError(
            code="VAL-AGW-097",
            kind="agents",
            message="session transition may not modify immutable session identity fields",
            details={"session-id": session_id, "rejected-fields": sorted(illegal)},
        )
    with _session_lock(project_root, session_id):
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
    """Append a served request and bump turn-count/last-activity.

    Idempotent: replaying finalization for a request-id already recorded
    returns the existing record unchanged — no second count increment, no
    duplicate timeline fact (duplicate/late terminal evidence must not
    create terminal side effects twice).
    """
    with _session_lock(project_root, session_id):
        record = read_session_record(project_root, session_id)
        request_ids = list(record.get("request-ids") or [])
        if request_id in request_ids:
            return record
        updated = dict(record)
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
