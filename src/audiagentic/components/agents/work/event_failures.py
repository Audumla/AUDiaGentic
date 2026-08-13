"""Redacted operational records for canonical event-ingress failures."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.observability.operational_records import append_operational_record
from audiagentic.foundation.time import now_iso_z

_FAILURE_PATH = Path(".audiagentic") / "runtime" / "agents" / "event-failures.ndjson"


def event_failure_path(project_root: Path) -> Path:
    return project_root / _FAILURE_PATH


def record_event_failure(
    project_root: Path,
    *,
    trigger_id: str,
    event_type: str,
    correlation_id: str | None,
    error_code: str,
) -> None:
    """Persist only safe event-failure metadata; never payload or prompt text."""
    append_operational_record(
        event_failure_path(project_root),
        {
            "timestamp": now_iso_z(),
            "correlation_id": correlation_id or "",
            "component": "agents",
            "trigger_id": trigger_id,
            "event_type": event_type,
            "error_code": error_code,
        },
    )


def read_event_failures(project_root: Path) -> list[dict[str, Any]]:
    path = event_failure_path(project_root)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
