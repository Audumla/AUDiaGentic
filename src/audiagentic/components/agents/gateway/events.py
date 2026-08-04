"""Agent Execution Gateway event trigger (AG12).

Subscribes to ``agents.execution.gateway.requested`` and normalizes it into the same
request contract used by the direct API (gateway.api.submit_execution_request)
— an event-triggered request and an MCP-submitted one produce identical
persisted records and go through the identical lifecycle event stream
(gateway.queue.queue publishes queued/started/completed/failed/cancelled/
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

from audiagentic.components.agents.gateway.event_topics import (
    EXECUTION_REJECTED_TOPIC,
    GATEWAY_CANCEL_REQUESTED_TOPIC,
    GATEWAY_REQUESTED_TOPIC,
)
from audiagentic.components.agents.gateway.mapping import first_present
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import get_bus

logger = logging.getLogger(__name__)

_REGISTERED = False
# Deliberately gateway-scoped, not the generic "agents.execution.requested" — that
# name is broad enough that an unrelated future publisher could accidentally
# trigger real provider dispatch by publishing to what looked like a neutral
# "an LLM request happened" marker (RV32 finding).


def _publish_rejected(reason: str, metadata: dict[str, Any]) -> None:
    """Reject a malformed event payload before any record is ever created —
    there is no request-id yet, so this carries only the reason and whatever
    correlation/subject metadata the publisher supplied (RV18 finding)."""
    get_bus().publish(
        EXECUTION_REJECTED_TOPIC,
        {"request-id": None, "error": {"code": "VAL-AGW-040", "message": reason, "kind": "agents"}},
        metadata=metadata,
    )


def _on_execution_requested(
    event_type: str, payload: dict[str, Any], metadata: dict[str, Any]
) -> None:
    """Normalize an agents.execution.gateway.requested event into a gateway request and submit it.

    Defaults to async — a request event returns via lifecycle events
    (agents.execution.completed/failed/...), not a return value. ``payload.blocking``
    opts into same-process blocking (rare: only when the publisher is willing
    to hold the event dispatch thread for the whole request — run_execution_request
    via the direct API/MCP tools is the normal way to get blocking behavior).
    """
    project_root_raw = first_present(payload, "project-root", "project_root")
    if not project_root_raw:
        logger.warning(
            "gateway request event missing project-root; rejecting",
            extra={"event_type": event_type},
        )
        _publish_rejected("payload missing required 'project-root'", metadata)
        return

    prompt_body = first_present(payload, "prompt-body", "prompt_body")
    if not prompt_body:
        logger.warning(
            "gateway request event missing prompt-body; rejecting", extra={"event_type": event_type}
        )
        _publish_rejected("payload missing required 'prompt-body'", metadata)
        return

    from audiagentic.components.agents.gateway.client import get_gateway_client

    project_root = Path(project_root_raw)
    execution_profile_id = first_present(payload, "execution-profile-id", "execution_profile_id")
    blocking = bool(payload.get("blocking"))
    source = first_present(payload, "source") or f"event:{GATEWAY_REQUESTED_TOPIC}"

    try:
        get_gateway_client().submit_execution_request(
            project_root,
            execution_profile_id=execution_profile_id,
            prompt_body=prompt_body,
            mode="blocking" if blocking else "async",
            source=source,
            # metadata flows straight into the persisted record, so
            # correlation_id/subject survive into every lifecycle event
            # agents_gateway_queue publishes for this request (AG12 spec).
            metadata=metadata,
        )
    except AudiaGenticError as exc:
        logger.warning(
            "gateway request event submission failed",
            extra={"event_type": event_type},
            exc_info=True,
        )
        _publish_rejected(exc.message, metadata)
    except Exception:  # noqa: BLE001
        # External boundary (Std 8): an unexpected exception here would
        # otherwise be silently swallowed by EventBus's subscriber isolation
        # with no agents.execution.rejected ever published — the caller would just
        # see nothing happen (RV32 finding).
        logger.error(
            "gateway request event submission raised unexpectedly",
            extra={"event_type": event_type},
            exc_info=True,
        )
        _publish_rejected(
            "unexpected error while submitting the gateway request (see server logs)", metadata
        )


def _on_cancel_requested(
    event_type: str, payload: dict[str, Any], metadata: dict[str, Any]
) -> None:
    """Cancel the gateway request named in an agents.execution.gateway.cancel-requested event.

    Owns only gateway request cancellation; the publisher (agent-jobs) owns
    the originating control event's durable audit — so this handler logs and
    returns on failure rather than dead-lettering. Never raises.
    """
    project_root_raw = first_present(payload, "project-root", "project_root")
    if not project_root_raw or not isinstance(project_root_raw, str):
        logger.warning(
            "gateway cancel event missing project-root; ignoring", extra={"event_type": event_type}
        )
        return

    request_id = first_present(payload, "request-id", "request_id")
    if not request_id or not isinstance(request_id, str):
        logger.warning(
            "gateway cancel event missing request-id; ignoring", extra={"event_type": event_type}
        )
        return

    from audiagentic.components.agents.gateway.client import get_gateway_client

    try:
        get_gateway_client().cancel_execution_request(Path(project_root_raw), request_id)
    except AudiaGenticError:
        logger.warning(
            "gateway cancel event failed",
            extra={"event_type": event_type, "request_id": request_id},
            exc_info=True,
        )
    except Exception:  # noqa: BLE001 — external boundary; handler never raises
        logger.error(
            "gateway cancel event raised unexpectedly",
            extra={"event_type": event_type, "request_id": request_id},
            exc_info=True,
        )


def register() -> None:
    """Subscribe to the gateway request/cancel topics. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return
    get_bus().subscribe(GATEWAY_REQUESTED_TOPIC, _on_execution_requested)
    get_bus().subscribe(GATEWAY_CANCEL_REQUESTED_TOPIC, _on_cancel_requested)
    _REGISTERED = True


register()
