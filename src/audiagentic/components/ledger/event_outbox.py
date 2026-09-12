"""Durable delivery intents for ``ledger.event.recorded`` projections."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.paths import ledger_fragments_dir
from audiagentic.foundation.event import DeliveryMode
from audiagentic.foundation.io import atomic_write_json, atomic_write_text
from audiagentic.foundation.paths.safety import resolve_user_path


def outbox_dir(project_root: Path) -> Path:
    return resolve_user_path(
        Path(".audiagentic") / "runtime" / "ledger" / "event-outbox",
        project_root=project_root,
        field_name="Ledger event outbox",
    )


def enqueue(
    project_root: Path,
    event_id: str,
    plan_item_ids: list[str],
    *,
    source: Any = None,
    timestamp_utc: str | None = None,
    event: dict[str, Any] | None = None,
) -> Path:
    """Persist one retryable projection intent before publishing it."""
    record = {
        "event-id": event_id,
        "plan-item-ids": list(plan_item_ids),
        "project-root": str(project_root),
        "source": source,
        "timestamp-utc": timestamp_utc,
    }
    if event is not None:
        record["event"] = dict(event)
    path = outbox_dir(project_root) / f"{event_id}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if event is not None and "event" not in existing:
            existing = {**existing, "event": dict(event)}
            atomic_write_json(path, existing)
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
            if root.resolve() != project_root.resolve():
                raise ValueError("ledger event outbox project root mismatch")
            fragment = ledger_fragments_dir(root) / f"{record['event-id']}.json"
            if not fragment.exists():
                event = record.get("event")
                if not isinstance(event, dict) or event.get("event-id") != record["event-id"]:
                    # Legacy intents without the authoritative event cannot
                    # safely be materialized; retain them for explicit retry.
                    failed += 1
                    break
                atomic_write_text(fragment, json.dumps(event, indent=2, sort_keys=True))
            publisher(
                str(record["event-id"]),
                list(record["plan-item-ids"]),
                root,
                source=record.get("source"),
                timestamp_utc=record.get("timestamp-utc"),
                raise_on_failure=True,
                delivery_mode=DeliveryMode.SYNC,
                propagate_subscriber_errors=True,
            )
            path.unlink(missing_ok=True)
            delivered += 1
        except Exception:  # noqa: BLE001 - durable retry intent remains
            failed += 1
            break
    return {"delivered": delivered, "failed": failed}


__all__ = ["drain", "enqueue", "outbox_dir"]
