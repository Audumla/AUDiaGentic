"""Release fragment recording."""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.events import publish_ledger_event_recorded
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_text
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


def _fragment_dir(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"


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
    fragment_path = _fragment_dir(project_root) / f"{event_id}.json"

    if fragment_path.exists():
        existing = json.loads(fragment_path.read_text(encoding="utf-8"))
        # git-commits is a mutable annotation — exclude from immutability check
        existing_core = {k: v for k, v in existing.items() if k != "git-commits"}
        event_core = {k: v for k, v in event.items() if k != "git-commits"}
        if existing_core != event_core:
            raise AudiaGenticError(
                code="CON-FRAGMENT-001",
                kind="release",
                message="fragment already exists with different content",
                details={"event-id": event_id},
            )
        plan_item_ids = event.get("plan-item-ids")
        if isinstance(plan_item_ids, list) and plan_item_ids:
            # Re-drive the projection on idempotent retries. The planning
            # consumer deduplicates by event ID, so this repairs a missed
            # async delivery without creating duplicate links.
            publish_ledger_event_recorded(
                event_id,
                plan_item_ids,
                project_root,
                source=event.get("source"),
                timestamp_utc=event.get("timestamp-utc"),
            )
        return {"fragment-path": str(fragment_path), "event-id": event_id, "status": "exists"}

    atomic_write_text(fragment_path, json.dumps(event, indent=2, sort_keys=True))

    plan_item_ids = event.get("plan-item-ids")
    if isinstance(plan_item_ids, list) and plan_item_ids:
        publish_ledger_event_recorded(
            event_id,
            plan_item_ids,
            project_root,
            source=event.get("source"),
            timestamp_utc=event.get("timestamp-utc"),
        )

    return {"fragment-path": str(fragment_path), "event-id": event_id, "status": "created"}
