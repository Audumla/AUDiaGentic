"""Release fragment recording."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.foundation.io import atomic_write_text


def _validate_change_event(payload: dict[str, Any]) -> None:
    schema = read_schema("change-event")
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise AudiaGenticError(
            code="VAL-FRAGMENT-001",
            kind="release",
            message="change event failed schema validation",
            details={"errors": [error.message for error in errors]},
        )


def _fragment_dir(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"


def record_change_event(project_root: Path, event: dict[str, Any]) -> dict[str, Any]:
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
        return {"fragment-path": str(fragment_path), "event-id": event_id, "status": "exists"}

    atomic_write_text(fragment_path, json.dumps(event, indent=2, sort_keys=True))
    return {"fragment-path": str(fragment_path), "event-id": event_id, "status": "created"}
