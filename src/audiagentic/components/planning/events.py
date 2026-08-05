"""Planning component event helpers."""
from __future__ import annotations

import logging
from pathlib import Path
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

LEDGER_EVENT_RECORDED = "ledger.event.recorded"

_registered_bus: Any | None = None


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


def _on_ledger_event_recorded(
    event_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    """Handle ledger.event.recorded — append ledger event ID to plan item's ledger-events section.

    For each plan-item-id in the payload, validates the item exists and appends
    the ledger event ID as a list item (e.g. '- chg_...') under the ledger-events
    body section. Bad IDs are logged and skipped; valid IDs are linked.
    """
    project_root = payload.get("project_root")
    if not isinstance(project_root, Path):
        logger.error(
            "ledger.event.recorded missing or invalid project_root",
            extra={"event_type": event_type},
        )
        return

    event_id = payload.get("event-id")
    plan_item_ids = payload.get("plan-item-ids", [])

    if not isinstance(event_id, str) or not isinstance(plan_item_ids, list):
        logger.error(
            "ledger.event.recorded missing event-id or plan-item-ids",
            extra={"event_type": event_type},
        )
        return

    from audiagentic.components.planning import planning_api
    from audiagentic.components.planning.item_store import require_item

    for item_id in plan_item_ids:
        if not isinstance(item_id, str):
            continue
        try:
            new_entry = f"- {event_id}"
            item_path = require_item(project_root, item_id)
            raw_item = item_path.read_text(encoding="utf-8")
            if any(line.strip() == new_entry for line in raw_item.splitlines()):
                logger.debug(
                    "ledger event already linked to plan item",
                    extra={"item_id": item_id, "event_id": event_id},
                )
                continue
            existing = planning_api.get_item(project_root, item_id)
            current_ledger = existing.get("ledger-events", "")
            updated_ledger = (
                current_ledger.rstrip() + "\n" + new_entry
                if current_ledger.strip()
                else new_entry
            )
            planning_api.update_item(project_root, item_id, {"ledger-events": updated_ledger})
            logger.info(
                "linked ledger event to plan item",
                extra={"item_id": item_id, "event_id": event_id},
            )
        except Exception:  # noqa: BLE001
            logger.error(
                "failed to link ledger event to plan item — skipping",
                extra={"item_id": item_id, "event_id": event_id},
                exc_info=True,
            )


def register() -> None:
    """Register the ledger.event.recorded subscription on the event bus."""
    global _registered_bus
    try:
        bus = get_bus()
        if _registered_bus is bus:
            return
        bus.subscribe(LEDGER_EVENT_RECORDED, _on_ledger_event_recorded)
        _registered_bus = bus
        logger.debug("subscribed to ledger.event.recorded")
    except Exception:  # noqa: BLE001
        logger.warning("failed to subscribe to ledger.event.recorded", exc_info=True)


register()
