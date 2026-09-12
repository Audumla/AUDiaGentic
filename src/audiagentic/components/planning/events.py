"""Planning component event helpers."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.foundation.event import DeliveryMode, get_bus
from audiagentic.foundation.io import atomic_write_json

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

_OUTBOX_RELATIVE = Path(".audiagentic") / "runtime" / "planning" / "outbox"


def _outbox_dir(project_root: Path) -> Path:
    return project_root / _OUTBOX_RELATIVE


def enqueue_planning_event(
    project_root: Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
) -> str:
    """Persist one planning event before attempting publication.

    The file is the delivery authority.  Publication is at-least-once: a
    process failure after subscriber execution and before acknowledgement may
    cause a duplicate, so consumers must use stable subject/event IDs.
    """
    stable_id = event_id or str(uuid.uuid4())
    durable_payload = dict(payload)
    durable_payload.setdefault("planning-event-id", stable_id)
    record = {
        "planning-event-id": stable_id,
        "event-type": event_type,
        "payload": durable_payload,
        "metadata": dict(metadata or {}),
    }
    directory = _outbox_dir(project_root)
    path = directory / f"{stable_id}.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"planning event outbox entry is corrupt: {path}") from exc
        if existing != record:
            raise ValueError(f"planning event ID already exists with different content: {stable_id}")
        return stable_id
    atomic_write_json(path, record)
    return stable_id


def drain_planning_outbox(project_root: Path) -> dict[str, int]:
    """Publish durable planning events and acknowledge successful delivery."""
    delivered = failed = 0
    directory = _outbox_dir(project_root)
    if not directory.exists():
        return {"delivered": 0, "failed": 0}
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("event record is not an object")
            get_bus().publish(
                str(record["event-type"]),
                dict(record["payload"]),
                metadata=dict(record.get("metadata") or {}),
                mode=DeliveryMode.SYNC,
            )
            path.unlink(missing_ok=True)
            delivered += 1
        except Exception:  # noqa: BLE001 - retain entry for reconciliation
            failed += 1
            logger.error(
                "failed to drain planning event outbox",
                extra={"path": str(path)},
                exc_info=True,
            )
            break
    return {"delivered": delivered, "failed": failed}


def publish_planning_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    subject_kind: str,
    subject_id: str,
    project_root: Path | None = None,
) -> None:
    """Persist and publish a planning event after storage mutation succeeds.

    ``project_root`` is required for durable delivery.  It remains optional to
    preserve compatibility for low-level callers that only have an in-memory
    event context; those callers retain the historical best-effort behavior.
    """
    metadata = {
        "source_component": COMPONENT_ID,
        "subject": {"kind": subject_kind, "id": subject_id},
    }
    if project_root is not None:
        try:
            enqueue_planning_event(
                project_root,
                event_type,
                payload,
                metadata=metadata,
            )
            drain_planning_outbox(project_root)
            return
        except Exception:  # noqa: BLE001 - durable entry remains for retry
            logger.error(
                "failed to persist or publish planning event",
                extra={"event_type": event_type, "subject_id": subject_id},
                exc_info=True,
            )
            return
    try:
        get_bus().publish(
            event_type,
            payload,
            metadata=metadata,
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

    from audiagentic.components.planning import item_store
    from audiagentic.foundation.io import atomic_write_text

    for item_id in plan_item_ids:
        if not isinstance(item_id, str):
            continue
        try:
            with item_store.item_identity_write_lock(project_root, item_id):
                item_path = item_store.require_item(project_root, item_id)
                fm, body = item_store.parse_frontmatter(
                    item_path.read_text(encoding="utf-8")
                )
                item_store.ensure_not_review(fm, item_id, "VAL-PLN-020")
                updated_body, linked = item_store.append_ledger_event(
                    body,
                    event_id,
                )
                normalized = updated_body != body
                if not linked and not normalized:
                    logger.debug(
                        "ledger event already linked to plan item",
                        extra={"item_id": item_id, "event_id": event_id},
                    )
                    continue
                if linked:
                    updated_body = item_store.append_change_log(
                        updated_body,
                        datetime.now(timezone.utc).isoformat(),
                        "updated-by",
                        "Updated: section:ledger-events",
                    )
                atomic_write_text(item_path, item_store.render_item(fm, updated_body))
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
