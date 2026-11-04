"""Change-event recording: one tracked, write-once event file per event."""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.current_events import (
    event_identity,
    event_write_lock,
    released_events,
    write_event,
)
from audiagentic.components.ledger.validation import validate_persisted_event
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.time import now_iso_z


def _validate_change_event(payload: dict[str, Any]) -> None:
    errors = validate_with_schema("change-event", payload)
    if errors:
        raise AudiaGenticError(
            code="VAL-FRAGMENT-001",
            kind="release",
            message="change event failed schema validation",
            details={"errors": errors},
        )
    # A recorded event is current by definition: it must be readable back as one.
    validate_persisted_event(payload, location="recorded event", role="current")


def _generate_event_id(desc: str | None = None) -> str:
    """Generate a unique event ID: chg_YYYYMMDD_HHMMSS_<desc>."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = f"_{desc}" if desc else ""
    rand = random.randint(1000, 9999)
    return f"chg_{ts}{suffix}_{rand}"


def _sanitize_filename(desc: str) -> str:
    """Sanitize a description for use in a filename.

    Replaces spaces with dashes and strips characters that are invalid on
    Windows (: < > | ? *) or problematic across platforms.
    """
    sanitized = desc[:30].lower().replace(" ", "-")
    sanitized = re.sub(r"[^a-z0-9_\-]", "", sanitized)
    return sanitized.strip("-_")


def record_change_event(project_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    if "timestamp-utc" not in event:
        event["timestamp-utc"] = now_iso_z()
    if "event-id" not in event:
        desc = event.get("user-summary-candidate", "")
        event["event-id"] = _generate_event_id(_sanitize_filename(desc) if desc else None)
    _validate_change_event(event)
    event_id = event["event-id"]
    with event_write_lock(project_root, event_id):
        return _record_change_event_locked(project_root, event)


def _record_change_event_locked(project_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    event_id = event["event-id"]
    released = released_events(project_root).get(event_id)
    if released is not None and event_identity(released) != event_identity(event):
        # Refuse before anything is written: the historical ledger is authoritative for a released id.
        raise AudiaGenticError(
            code="CON-ARCHIVE-003", kind="release",
            message="event-id is already released with different content",
            details={"event-id": event_id},
        )
    path, status = write_event(project_root, event)
    return {"event-path": str(path), "event-id": event_id, "status": status}
