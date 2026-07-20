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

from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_event_topics import (
    TURN_MODEL_COMPLETED_TOPIC,
    TURN_MODEL_STARTED_TOPIC,
    TURN_TOOL_COMPLETED_TOPIC,
    TURN_TOOL_STARTED_TOPIC,
)
from audiagentic.foundation.transports.acp import AcpEvent

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

    Keys on the transport's CANONICAL kinds only (RV679: the old mapping
    depended on raw wire kinds leaking through the normalization layer).
    Dedupes model.started to once per turn and tool.started to once per
    tool-call id; emits tool.completed for both completed and failed statuses
    with the status attached; emits model.completed from the terminal result
    event, which the transport now delivers through the callback.
    """

    def __init__(self) -> None:
        self._model_started = False
        self._tools_started: set[str] = set()
        self._tools_finished: set[str] = set()

    @staticmethod
    def _acp_ext(event: AcpEvent) -> dict[str, Any]:
        ext = event.ext.get("acp") if event.ext else None
        return ext if isinstance(ext, dict) else {}

    def _tool_identity(self, event: AcpEvent) -> str:
        acp = self._acp_ext(event)
        tool_call_id = acp.get("tool_call_id")
        if tool_call_id is None:
            payload = acp.get("payload")
            if isinstance(payload, dict):
                tool_call_id = payload.get("toolCallId") or payload.get("tool_call_id")
        return str(tool_call_id) if tool_call_id is not None else "unidentified"

    def _tool_status(self, event: AcpEvent) -> str | None:
        acp = self._acp_ext(event)
        status = acp.get("status")
        if status is None:
            payload = acp.get("payload")
            if isinstance(payload, dict):
                status = payload.get("status")
        return str(status) if status is not None else None

    def resolve(self, event: AcpEvent) -> tuple[str, dict[str, Any]] | None:
        """Return (topic, extra-payload) for a projectable event, else None."""
        if event.kind in ("thought", "assistant-message"):
            if self._model_started:
                return None
            self._model_started = True
            return TURN_MODEL_STARTED_TOPIC, {}
        if event.kind == "result":
            return TURN_MODEL_COMPLETED_TOPIC, {}
        if event.kind == "tool-call":
            status = self._tool_status(event)
            identity = self._tool_identity(event)
            if status in _TOOL_ACTIVE_STATUSES:
                if identity in self._tools_started:
                    return None
                self._tools_started.add(identity)
                return TURN_TOOL_STARTED_TOPIC, {"tool-call-id": identity}
            if status in _TOOL_TERMINAL_STATUSES:
                if identity in self._tools_finished:
                    return None
                self._tools_finished.add(identity)
                return TURN_TOOL_COMPLETED_TOPIC, {
                    "tool-call-id": identity,
                    "status": status,
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
    event: AcpEvent,
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
        "sequence": event.sequence,
        "kind": event.kind,
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
        session_store.record_session_timeline(
            project_root, session_id, f"session.turn.{event.kind}", state="active",
            attributes=attrs,
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "failed to record turn timeline event",
            extra={"session-id": session_id, "kind": event.kind},
            exc_info=True,
        )


def _make_on_event_callback(
    session_id: str,
    project_root: Path,
    request_id: str | None,
    agent_profile_id: str,
    correlation_id: str | None,
    *,
    activity_marker: Callable[[], None] | None = None,
) -> Any:
    """Build an on_event callback for transport.prompt that publishes normalized events.

    The callback is observational only — it never completes a turn, releases a slot,
    or changes session reuse policy (AS18 scope boundary). ``activity_marker``
    is invoked for EVERY event (mapped or not) so the runtime's in-turn
    liveness clock reflects real transport activity (RV680 silence watchdog).
    """
    projector = _TurnEventProjector()

    async def _on_event(event: AcpEvent) -> None:
        if activity_marker is not None:
            activity_marker()
        resolved = projector.resolve(event)
        if resolved is None:
            return
        topic, extra = resolved

        # Redacted evidence envelope — no prompt text, output, tool args, or secrets
        payload: dict[str, Any] = {
            "session-id": session_id,
            "agent-profile-id": agent_profile_id,
            "request-id": request_id,
            "kind": event.kind,
            "sequence": event.sequence,
            "native_kind": event.ext.get("acp", {}).get("raw_kind") if event.ext else None,
            "semantic-strength": _TURN_EVENT_SEMANTIC_STRENGTH,
            "verification-tier": _TURN_EVENT_VERIFICATION_TIER,
            **extra,
        }

        _publish_turn_event(topic, payload, correlation_id=correlation_id)
        # SH15: pass tool-call-id and status into the timeline for richer progress summary
        extra_attrs: dict[str, Any] | None = None
        if event.kind == "tool-call":
            acp_ext = event.ext.get("acp") if event.ext else None
            if isinstance(acp_ext, dict):
                extra_attrs = {}
                tid = acp_ext.get("tool_call_id") or acp_ext.get("toolCallId")
                if tid is not None:
                    extra_attrs["tool-call-id"] = str(tid)
                status = acp_ext.get("status")
                if status is not None:
                    extra_attrs["status"] = str(status)
        _record_turn_timeline(project_root, session_id, request_id, correlation_id, event, topic,
                             extra_attrs=extra_attrs)

    return _on_event
