"""Turn-event projection and publishing extracted from agents_gateway_sessions.py.

Owns the per-turn event pipeline: constants, session/turn event publishing,
the _TurnEventProjector state machine, timeline recording, and the on_event
callback builder. Moved here to reduce the line count of sessions.py while
keeping cohesion within each module (SH18).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway.event_topics import (
    TURN_MODEL_COMPLETED_TOPIC,
    TURN_MODEL_IN_PROGRESS_TOPIC,
    TURN_MODEL_STARTED_TOPIC,
    TURN_TOOL_COMPLETED_TOPIC,
    TURN_TOOL_STARTED_TOPIC,
)
from audiagentic.components.agents.gateway.session import sessions_store as session_store
from audiagentic.foundation.transports.agent_session import (
    TransportObservation,
    TransportObservationKind,
)

logger = logging.getLogger(__name__)

# AS19/RV679: runtime events may report observations but cannot self-attest
# semantic strength or verification tier. Until provider-declared,
# surface/version-specific observability resolution lands (AS19), every
# projection is honestly labelled unknown — never "precise"/"execution".
_TURN_EVENT_SEMANTIC_STRENGTH = "unknown"
_TURN_EVENT_VERIFICATION_TIER = "unknown"

# Tool statuses that mean the tool finished; carried on the completed event so
# observers can distinguish success from failure (RV679: failed was invisible).
_TOOL_TERMINAL_STATUSES = {"completed", "failed"}
_TOOL_ACTIVE_STATUSES = {None, "pending", "in_progress"}


def _event_metadata(correlation_id: str | None) -> dict[str, str]:
    return {"correlation_id": correlation_id} if correlation_id else {}


def _publish_session_event(
    topic: str,
    payload: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> None:
    """Publish a session lifecycle event. Never raises (RV38 pattern)."""
    from audiagentic.foundation.event import get_bus

    try:
        get_bus().publish(topic, payload, metadata=_event_metadata(correlation_id))
    except Exception:  # noqa: BLE001
        logger.error(
            "failed to publish session lifecycle event",
            extra={"session-id": payload.get("session-id"), "event": topic},
            exc_info=True,
        )


class _TurnEventProjector:
    """Stateful per-turn projection of canonical transport events to turn topics.

    Keys on the transport's CANONICAL kinds only (TransportObservationKind).
    Dedupes model.started to once per turn and tool.started to once per
    tool-call id; emits tool.completed for both completed and failed statuses
    with the status attached; emits model.completed from the terminal
    observation, which the transport now delivers through the callback.
    """

    def __init__(self) -> None:
        self._model_started = False
        self._tools_started: set[str] = set()
        self._tools_finished: set[str] = set()

    def resolve(self, obs: TransportObservation) -> tuple[str, dict[str, Any]] | None:
        """Return (topic, extra-payload) for a projectable observation, else None."""
        if obs.kind == TransportObservationKind.ACTIVITY:
            if self._model_started:
                return None
            self._model_started = True
            return TURN_MODEL_STARTED_TOPIC, {}
        if obs.kind == TransportObservationKind.IN_PROGRESS:
            return TURN_MODEL_IN_PROGRESS_TOPIC, {
                "model_activity": obs.attributes.get("model_activity", "") if obs.attributes else "",
            }
        if obs.kind == TransportObservationKind.TERMINAL:
            return TURN_MODEL_COMPLETED_TOPIC, {}
        if obs.kind == TransportObservationKind.TOOL_REQUESTED:
            tool_call_id = obs.attributes.get("tool_call_id") if obs.attributes else None
            status = obs.attributes.get("tool_status") if obs.attributes else None
            identity = str(tool_call_id) if tool_call_id is not None else "unidentified"
            if status in _TOOL_ACTIVE_STATUSES:
                if identity in self._tools_started:
                    return None
                self._tools_started.add(identity)
                return TURN_TOOL_STARTED_TOPIC, {"tool-call-id": identity}
        if obs.kind == TransportObservationKind.TOOL_FINISHED:
            tool_call_id = obs.attributes.get("tool_call_id") if obs.attributes else None
            status = obs.attributes.get("tool_status") if obs.attributes else None
            identity = str(tool_call_id) if tool_call_id is not None else "unidentified"
            if status in _TOOL_TERMINAL_STATUSES:
                if identity in self._tools_finished:
                    return None
                self._tools_finished.add(identity)
                return TURN_TOOL_COMPLETED_TOPIC, {
                    "tool-call-id": identity,
                    "status": str(status) if status else "",
                }
        return None


def _publish_turn_event(
    topic: str,
    payload: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> None:
    """Publish an intra-turn event. Never raises (RV38 pattern)."""
    from audiagentic.foundation.event import get_bus

    try:
        get_bus().publish(topic, payload, metadata=_event_metadata(correlation_id))
    except Exception:  # noqa: BLE001
        logger.error(
            "failed to publish turn event",
            extra={"session-id": payload.get("session-id"), "event": topic},
            exc_info=True,
        )


def _record_turn_timeline(
    project_root: Path,
    session_id: str,
    request_id: str | None,
    correlation_id: str | None,
    obs: TransportObservation,
    topic: str,
    *,
    extra_attrs: dict[str, Any] | None = None,
) -> None:
    """Record a best-effort per-turn timeline event. Never raises.

    ``extra_attrs`` are additional scalar attributes merged into the
    timeline entry (SH15: tool-call-id / status for richer progress summary).
    """
    attrs = {
        "request-id": request_id,
        "sequence": obs.sequence,
        "kind": obs.kind.value if hasattr(obs.kind, "value") else str(obs.kind),
        "native-topic": topic,
        "semantic-strength": _TURN_EVENT_SEMANTIC_STRENGTH,
        "verification-tier": _TURN_EVENT_VERIFICATION_TIER,
        "correlation-id": correlation_id,
    }
    if extra_attrs:
        for k, v in extra_attrs.items():
            if isinstance(v, (str, int, float, bool)):
                attrs[k] = v
    try:
        kind_str = obs.kind.value if hasattr(obs.kind, "value") else str(obs.kind)
        session_store.record_session_timeline(
            project_root, session_id, f"session.turn.{kind_str}", state="active",
            attributes=attrs,
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "failed to record turn timeline event",
            extra={"session-id": session_id, "kind": obs.kind},
            exc_info=True,
        )


def _make_on_event_callback(
    session_id: str,
    project_root: Path,
    request_id: str | None,
    execution_profile_id: str,
    correlation_id: str | None,
    *,
    activity_marker: Callable[[], None] | None = None,
    latest_event_recorder: Callable[[str, dict[str, Any]], None] | None = None,
    activity_relay: Any | None = None,
) -> Any:
    """Build an on_event callback for transport.prompt that publishes normalized events.

    The callback is observational only — it never completes a turn, releases a slot,
    or changes session reuse policy (AS18 scope boundary). ``activity_marker``
    is invoked for EVERY observation (mapped or not) so the runtime's in-turn
    liveness clock reflects real transport activity (RV680 silence watchdog).
    ``latest_event_recorder`` is invoked with (topic, payload) only for
    projectable (mapped) observations, so a live session handle can track its most
    recent turn event for diagnostics (request_runtime_status).
    """
    projector = _TurnEventProjector()

    async def _on_event(obs: TransportObservation) -> None:
        if activity_marker is not None:
            activity_marker()
        if activity_relay is not None:
            try:
                activity_relay.observe_provider(
                    source="session-transport",
                    source_instance=f"session:{session_id}:turn:{request_id or 'unknown'}",
                    source_sequence=obs.sequence,
                    phase=(obs.kind.value if hasattr(obs.kind, "value") else str(obs.kind)),
                )
            except Exception:  # noqa: BLE001 - liveness must never break a turn
                pass
        resolved = projector.resolve(obs)
        if resolved is None:
            return
        topic, extra = resolved

        # Redacted evidence envelope — no prompt text, output, tool args, or secrets
        kind_str = obs.kind.value if hasattr(obs.kind, "value") else str(obs.kind)
        payload: dict[str, Any] = {
            "session-id": session_id,
            "execution-profile-id": execution_profile_id,
            "request-id": request_id,
            "kind": kind_str,
            "sequence": obs.sequence,
            "semantic-strength": _TURN_EVENT_SEMANTIC_STRENGTH,
            "verification-tier": _TURN_EVENT_VERIFICATION_TIER,
            **extra,
        }

        _publish_turn_event(topic, payload, correlation_id=correlation_id)
        if latest_event_recorder is not None:
            latest_event_recorder(topic, payload)
        # SH15: pass tool-call-id and status into the timeline for richer progress summary
        extra_attrs: dict[str, Any] | None = None
        if obs.kind == TransportObservationKind.TOOL_REQUESTED or obs.kind == TransportObservationKind.TOOL_FINISHED:
            if obs.attributes:
                extra_attrs = {}
                tid = obs.attributes.get("tool_call_id")
                if tid is not None:
                    extra_attrs["tool-call-id"] = str(tid)
                status = obs.attributes.get("tool_status")
                if status is not None:
                    extra_attrs["status"] = str(status)
        _record_turn_timeline(project_root, session_id, request_id, correlation_id, obs, topic,
                             extra_attrs=extra_attrs)

    return _on_event
