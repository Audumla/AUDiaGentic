"""One-time migration of events the pre-per-event ledger left in its runtime directory.

Before LE03 an event first lived as a runtime fragment (``fragments/<event-id>.json``) or, with plan-item links, as the
full event inside a durable outbox intent (``event-outbox/<event-id>.json``), and only then reached the shared ledger.
An upgraded machine can still hold events that never got that far. Each one is materialized as a tracked event file
(unless the historical ledger already released it), verified, and only then deleted; anything that cannot be migrated
is left in place and reported, never discarded. Once a release has shipped, a project with nothing left here makes
this a no-op, and it can be removed in a later release.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.current_events import (
    event_identity,
    event_write_lock,
    parse_event_file,
    released_events,
    write_event,
)
from audiagentic.components.ledger.paths import ledger_runtime_dir
from audiagentic.components.ledger.validation import validate_persisted_event
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _legacy_event(path: Path, outbox: bool) -> dict[str, Any] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    event = record.get("event") if outbox and isinstance(record, dict) else record
    if not isinstance(event, dict) or not isinstance(event.get("event-id"), str):
        return None
    return event


def migrate_legacy_runtime(project_root: Path) -> dict[str, Any]:
    """Materialize retained fragments and outbox events; returns counts and the names left in place."""
    runtime = ledger_runtime_dir(project_root)
    released = released_events(project_root)
    migrated = already_released = 0
    left: list[str] = []
    for folder, outbox in (("fragments", False), ("event-outbox", True)):
        directory = runtime / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            event = _legacy_event(path, outbox)
            if event is None:
                left.append(f"{folder}/{path.name}")
                continue
            try:
                validate_persisted_event(event, location=f"{folder}/{path.name}", role="current")
                prior = released.get(event["event-id"])
                if prior is not None:
                    if event_identity(prior) != event_identity(event):
                        raise AudiaGenticError(
                            code="CON-ARCHIVE-003", kind="release",
                            message="retained event conflicts with a released event", details={"event-id": event["event-id"]},
                        )
                    already_released += 1
                else:
                    with event_write_lock(project_root, event["event-id"]):
                        target, _ = write_event(project_root, event)
                        parse_event_file(target, target.read_text(encoding="utf-8"))  # verify before deleting
                    migrated += 1
            except AudiaGenticError:
                left.append(f"{folder}/{path.name}")
                continue
            path.unlink(missing_ok=True)
        for leftover in directory.glob(".*.lock"):
            leftover.unlink(missing_ok=True)
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return {"migrated": migrated, "already-released": already_released, "left-in-place": left}


__all__ = ["migrate_legacy_runtime"]
