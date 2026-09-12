"""Durable delivery intents for ``ledger.event.recorded`` projections."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.event import DeliveryMode
from audiagentic.foundation.io import atomic_write_json


def outbox_dir(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "event-outbox"


def enqueue(
    project_root: Path,
    event_id: str,
    plan_item_ids: list[str],
    *,
    source: Any = None,
    timestamp_utc: str | None = None,
) -> Path:
    """Persist one retryable projection intent before publishing it."""
    record = {
        "event-id": event_id,
        "plan-item-ids": list(plan_item_ids),
        "project-root": str(project_root),
        "source": source,
        "timestamp-utc": timestamp_utc,
    }
    path = outbox_dir(project_root) / f"{event_id}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != record:
            raise ValueError(f"ledger event outbox ID already exists with different content: {event_id}")
        return path
    atomic_write_json(path, record)
    return path


def drain(project_root: Path, *, publisher: Any | None = None) -> dict[str, int]:
    """Retry pending ledger-to-planning deliveries; leave failures pending."""
    if publisher is None:
        from audiagentic.components.ledger.events import publish_ledger_event_recorded

        publisher = publish_ledger_event_recorded

    delivered = failed = 0
    directory = outbox_dir(project_root)
    if not directory.exists():
        return {"delivered": 0, "failed": 0}
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            root = Path(record["project-root"])
            publisher(
                str(record["event-id"]),
                list(record["plan-item-ids"]),
                root,
                source=record.get("source"),
                timestamp_utc=record.get("timestamp-utc"),
                raise_on_failure=True,
                delivery_mode=DeliveryMode.SYNC,
            )
            path.unlink(missing_ok=True)
            delivered += 1
        except Exception:  # noqa: BLE001 - durable retry intent remains
            failed += 1
            break
    return {"delivered": delivered, "failed": failed}


__all__ = ["drain", "enqueue", "outbox_dir"]
