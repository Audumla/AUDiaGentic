"""Agent LLM Gateway event trigger (AG12).

Subscribes to ``agents.llm.gateway.requested`` and normalizes it into the same
request contract used by the direct API (agents_gateway_api.submit_llm_request)
— an event-triggered request and an MCP-submitted one produce identical
persisted records and go through the identical lifecycle event stream
(agents_gateway_queue publishes queued/started/completed/failed/cancelled/
rejected for every request regardless of origin — this module only handles
the inbound trigger, not the outbound lifecycle events).

Self-registers at import time via register(), mirroring the established
pattern (audiagentic.components.memory.memory_observer,
audiagentic.components.coding_lsp.coding_lsp_bootstrap): get_bus() is a plain
lazy singleton with no initialization-order dependency, so there is no hazard
in subscribing during module import — this is the codebase's proven
convention, not a deferred-registration workaround.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import get_bus

logger = logging.getLogger(__name__)

_REGISTERED = False
# Deliberately gateway-scoped, not the generic "agents.llm.requested" — that
# name is broad enough that an unrelated future publisher could accidentally
# trigger real provider dispatch by publishing to what looked like a neutral
# "an LLM request happened" marker (RV32 finding).
_REQUESTED_TOPIC = "agents.llm.gateway.requested"


def _payload_get(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _publish_rejected(reason: str, metadata: dict[str, Any]) -> None:
    """Reject a malformed event payload before any record is ever created —
    there is no request-id yet, so this carries only the reason and whatever
    correlation/subject metadata the publisher supplied (RV18 finding)."""
    get_bus().publish(
        "agents.llm.rejected",
        {"request-id": None, "error": {"code": "VAL-AGW-040", "message": reason, "kind": "agents"}},
        metadata=metadata,
    )


def _on_llm_requested(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Normalize an agents.llm.gateway.requested event into a gateway request and submit it.

    Defaults to async — a request event returns via lifecycle events
    (agents.llm.completed/failed/...), not a return value. ``payload.blocking``
    opts into same-process blocking (rare: only when the publisher is willing
    to hold the event dispatch thread for the whole request — run_llm_request
    via the direct API/MCP tools is the normal way to get blocking behavior).
    """
    project_root_raw = _payload_get(payload, "project-root", "project_root")
    if not project_root_raw:
        logger.warning("gateway request event missing project-root; rejecting", extra={"event_type": event_type})
        _publish_rejected("payload missing required 'project-root'", metadata)
        return

    prompt_body = _payload_get(payload, "prompt-body", "prompt_body")
    if not prompt_body:
        logger.warning("gateway request event missing prompt-body; rejecting", extra={"event_type": event_type})
        _publish_rejected("payload missing required 'prompt-body'", metadata)
        return

    from audiagentic.components.agents import agents_gateway_api as gateway

    project_root = Path(project_root_raw)
    agent_profile_id = _payload_get(payload, "agent-profile-id", "agent_profile_id")
    fallback_profile_ids = _payload_get(payload, "fallback-profile-ids", "fallback_profile_ids")
    blocking = bool(payload.get("blocking"))
    source = _payload_get(payload, "source") or f"event:{_REQUESTED_TOPIC}"

    try:
        gateway.submit_llm_request(
            project_root,
            agent_profile_id=agent_profile_id,
            prompt_body=prompt_body,
            mode="blocking" if blocking else "async",
            fallback_profile_ids=fallback_profile_ids,
            source=source,
            # metadata flows straight into the persisted record, so
            # correlation_id/subject survive into every lifecycle event
            # agents_gateway_queue publishes for this request (AG12 spec).
            metadata=metadata,
        )
    except AudiaGenticError as exc:
        logger.warning(
            "gateway request event submission failed", extra={"event_type": event_type}, exc_info=True,
        )
        _publish_rejected(exc.message, metadata)
    except Exception:  # noqa: BLE001
        # External boundary (Std 8): an unexpected exception here would
        # otherwise be silently swallowed by EventBus's subscriber isolation
        # with no agents.llm.rejected ever published — the caller would just
        # see nothing happen (RV32 finding).
        logger.error(
            "gateway request event submission raised unexpectedly", extra={"event_type": event_type}, exc_info=True,
        )
        _publish_rejected("unexpected error while submitting the gateway request (see server logs)", metadata)


def register() -> None:
    """Subscribe to agents.llm.gateway.requested. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return
    get_bus().subscribe(_REQUESTED_TOPIC, _on_llm_requested)
    _REGISTERED = True


register()
