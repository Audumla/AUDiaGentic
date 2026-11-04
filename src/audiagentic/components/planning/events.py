"""Planning component event helpers."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from audiagentic.foundation.event import DeliveryMode, get_bus
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.paths.names import RUNTIME_RELATIVE
from audiagentic.foundation.paths.safety import resolve_user_path

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


_OUTBOX_RELATIVE = RUNTIME_RELATIVE / "planning" / "outbox"


def _outbox_dir(project_root: Path) -> Path:
    return resolve_user_path(
        _OUTBOX_RELATIVE,
        project_root=project_root,
        field_name="Planning event outbox",
    )


def build_planning_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    subject_kind: str,
    subject_id: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build a stable event intent that can be journaled with a mutation."""
    return {
        "event-id": event_id or str(uuid.uuid4()),
        "event-type": event_type,
        "payload": dict(payload),
        "metadata": {
            "source_component": COMPONENT_ID,
            "subject": {"kind": subject_kind, "id": subject_id},
        },
    }


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
                propagate_subscriber_errors=True,
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
    event_id: str | None = None,
) -> None:
    """Persist and publish a planning event after storage mutation succeeds.

    ``project_root`` is required for durable delivery.  It remains optional to
    preserve compatibility for low-level callers that only have an in-memory
    event context; those callers retain the historical best-effort behavior.
    """
    intent = build_planning_event(
        event_type,
        payload,
        subject_kind=subject_kind,
        subject_id=subject_id,
        event_id=event_id,
    )
    if project_root is not None:
        try:
            enqueue_planning_event(
                project_root,
                event_type,
                payload,
                metadata=intent["metadata"],
                event_id=intent["event-id"],
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
            metadata=intent["metadata"],
            mode=DeliveryMode.ASYNC,
        )
    except Exception:  # noqa: BLE001
        logger.error(
            "failed to publish planning event",
            extra={"event_type": event_type, "subject_id": subject_id},
            exc_info=True,
        )


def publish_planning_event_intent(project_root: Path, intent: dict[str, Any]) -> None:
    """Publish a previously journaled event using its stable identity."""
    subject = intent["metadata"]["subject"]
    publish_planning_event(
        str(intent["event-type"]),
        dict(intent["payload"]),
        subject_kind=str(subject["kind"]),
        subject_id=str(subject["id"]),
        project_root=project_root,
        event_id=str(intent["event-id"]),
    )
