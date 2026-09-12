"""Ledger component event helpers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.event import DeliveryMode, get_bus

logger = logging.getLogger(__name__)

COMPONENT_ID = "agent-ledger"

LEDGER_EVENT_RECORDED = "ledger.event.recorded"


def publish_ledger_event_recorded(
    event_id: str,
    plan_item_ids: list[str],
    project_root: Path,
    *,
    source: Any = None,
    timestamp_utc: str | None = None,
    raise_on_failure: bool = False,
    delivery_mode: DeliveryMode = DeliveryMode.ASYNC,
    propagate_subscriber_errors: bool = False,
) -> bool:
    """Publish ledger.event.recorded after a change event is successfully recorded.

    Used to drive automatic ledger-to-plan linkage: the planning component
    subscribes and appends the ledger event ID to each item's ledger-events section.
    """
    try:
        payload = {
            "event-id": event_id,
            "plan-item-ids": plan_item_ids,
            "project_root": project_root,
            "source": source,
            "timestamp-utc": timestamp_utc,
        }
        if propagate_subscriber_errors:
            payload["durable-projection"] = True
        get_bus().publish(
            LEDGER_EVENT_RECORDED,
            payload,
            metadata={
                "source_component": COMPONENT_ID,
                "subject": {"kind": "ledger-event", "id": event_id},
                "provenance": {"source": source, "timestamp-utc": timestamp_utc},
            },
            mode=delivery_mode,
            propagate_subscriber_errors=propagate_subscriber_errors,
        )
        return True
    except Exception:  # noqa: BLE001
        logger.error(
            "failed to publish ledger.event.recorded",
            extra={"event-id": event_id, "plan-item-ids": plan_item_ids},
            exc_info=True,
        )
        if raise_on_failure:
            raise
        return False
