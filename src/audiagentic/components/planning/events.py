"""Planning component event helpers."""
from __future__ import annotations

import logging
from typing import Any

from audiagentic.foundation.event import DeliveryMode, get_bus

logger = logging.getLogger(__name__)

COMPONENT_ID = "agent-planning"

PLANNING_ITEM_CREATED = "planning.item.created"
PLANNING_ITEM_UPDATED = "planning.item.updated"
PLANNING_ITEM_STATE_CHANGED = "planning.item.state.changed"
PLANNING_ITEM_DELETED = "planning.item.deleted"

PLANNING_REVIEW_CREATED = "planning.review.created"
PLANNING_REVIEW_UPDATED = "planning.review.updated"
PLANNING_REVIEW_STATE_CHANGED = "planning.review.state.changed"
PLANNING_REVIEW_DELETED = "planning.review.deleted"


def publish_planning_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    subject_kind: str,
    subject_id: str,
) -> None:
    """Publish a best-effort planning event after storage mutation succeeds."""
    try:
        get_bus().publish(
            event_type,
            payload,
            metadata={
                "source_component": COMPONENT_ID,
                "subject": {"kind": subject_kind, "id": subject_id},
            },
            mode=DeliveryMode.ASYNC,
        )
    except Exception:  # noqa: BLE001
        logger.error(
            "failed to publish planning event",
            extra={"event_type": event_type, "subject_id": subject_id},
            exc_info=True,
        )
