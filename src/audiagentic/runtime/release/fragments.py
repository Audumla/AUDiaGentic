"""Release fragment recording."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.contracts.schema_registry import read_schema


def _validate_change_event(payload: dict[str, Any]) -> None:
    schema = read_schema("change-event")
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise AudiaGenticError(
            code="RLS-VALIDATION-001",
            kind="validation",
            message="change event failed schema validation",
            details={"errors": [error.message for error in errors]},
        )


def _fragment_dir(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def record_change_event(project_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    _validate_change_event(event)
    event_id = event["event-id"]
    fragment_path = _fragment_dir(project_root) / f"{event_id}.json"

    if fragment_path.exists():
        existing = json.loads(fragment_path.read_text(encoding="utf-8"))
        if existing != event:
            raise AudiaGenticError(
                code="RLS-BUSINESS-001",
                kind="business-rule",
                message="fragment already exists with different content",
                details={"event-id": event_id},
            )
        return {"fragment-path": str(fragment_path), "event-id": event_id, "status": "exists"}

    _write_atomic(fragment_path, event)
    return {"fragment-path": str(fragment_path), "event-id": event_id, "status": "created"}
