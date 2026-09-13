"""Strict validation for persisted ledger records."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema


def validate_persisted_event(event: object, *, location: str) -> dict[str, Any]:
    """Validate one persisted ledger event and raise a typed integrity error."""
    if not isinstance(event, dict):
        raise AudiaGenticError(
            code="CON-LEDGER-002", kind="release",
            message="persisted ledger entry is not an object",
            details={"location": location},
        )
    errors = validate_with_schema("change-event", event)
    if errors:
        raise AudiaGenticError(
            code="CON-LEDGER-003", kind="release",
            message="persisted ledger entry failed schema validation",
            details={"location": location, "event-id": event.get("event-id"), "errors": errors},
        )
    return event


def load_persisted_events(path: Path) -> list[dict[str, Any]]:
    """Load and validate every non-empty NDJSON line; never silently drop data."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.strip() == "[]":
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AudiaGenticError(
                code="CON-LEDGER-004", kind="release",
                message="persisted ledger contains invalid JSON",
                details={"path": str(path), "line": line_number},
            ) from exc
        events.append(validate_persisted_event(value, location=f"{path}:{line_number}"))
    return events
