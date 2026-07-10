"""Ledger component event helpers."""
from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.foundation.event import DeliveryMode, get_bus

logger = logging.getLogger(__name__)

COMPONENT_ID = "agent-ledger"

LEDGER_EVENT_RECORDED = "ledger.event.recorded"


def publish_ledger_event_recorded(
    event_id: str,
    plan_item_ids: list[str],
    project_root: Path,
) -> None:
    """Publish ledger.event.recorded after a change event is successfully recorded.

    Used to drive automatic ledger-to-plan linkage: the planning component
    subscribes and appends the ledger event ID to each item's ledger-events section.
    """
    try:
        get_bus().publish(
            LEDGER_EVENT_RECORDED,
            {"event-id": event_id, "plan-item-ids": plan_item_ids, "project_root": project_root},
            metadata={
                "source_component": COMPONENT_ID,
                "subject": {"kind": "ledger-event", "id": event_id},
            },
            mode=DeliveryMode.ASYNC,
        )
    except Exception:  # noqa: BLE001
        logger.error(
            "failed to publish ledger.event.recorded",
            extra={"event-id": event_id, "plan-item-ids": plan_item_ids},
            exc_info=True,
        )
