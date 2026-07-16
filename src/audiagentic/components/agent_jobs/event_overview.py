"""Read-only operator overview for event-driven jobs (EDJ14).

Aggregates the trigger-audit sidecar written by ``event_observer.py`` and the
persisted job records into one on-demand summary. This module only reads —
the audit record shape is owned by the writer and must not be changed here.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs import jobs_store as store
from audiagentic.foundation.io import load_ndjson

logger = logging.getLogger(__name__)

_TRIGGER_AUDIT_PATH = Path(".audiagentic") / "runtime" / "agent-jobs" / "trigger-audit.ndjson"

_KNOWN_STATUSES = ("fired", "suppressed", "failed")
_MAX_RECENT_FAILURES = 5


def _load_audit_entries(project_root: Path) -> list[dict[str, Any]]:
    path = project_root / _TRIGGER_AUDIT_PATH
    try:
        return load_ndjson(path)
    except Exception:  # noqa: BLE001 — absent/corrupt runtime state must not raise
        logger.warning(
            "Failed to read trigger-audit file for overview",
            extra={"path": str(path)},
            exc_info=True,
        )
        return []


def _load_event_jobs(project_root: Path) -> list[dict[str, Any]]:
    try:
        records = store.list_job_records(project_root)
    except Exception:  # noqa: BLE001 — absent/corrupt runtime state must not raise
        logger.warning("Failed to list job records for overview", exc_info=True)
        return []
    # Event provenance: build_job_from_event persists an "event-source" block.
    return [r for r in records if isinstance(r.get("event-source"), dict)]


def event_jobs_overview(project_root: Path) -> dict[str, Any]:
    """Aggregate trigger-audit entries and event-origin job records.

    Returns the stable shape::

        {
          "by_trigger": {trigger_id: {"fired": int, "suppressed": int, "failed": int}},
          "jobs_by_state": {state: int},
          "recent_failures": [
            {trigger_id, event_type, correlation_id, error_code, error_message}
          ],
        }

    Missing audit files or jobs directories yield empty aggregates; this
    surface never raises for absent runtime state. ``recent_failures`` is
    newest-first, capped at 5, with the error message redacted — no payloads,
    prompts, metadata, or raw record objects are ever returned.
    """
    by_trigger: dict[str, dict[str, int]] = {}
    failures: list[dict[str, Any]] = []

    for entry in _load_audit_entries(project_root):
        status = entry.get("status")
        if status not in _KNOWN_STATUSES:
            continue
        trigger_id = str(entry.get("trigger_id") or "")
        counts = by_trigger.setdefault(
            trigger_id, {"fired": 0, "suppressed": 0, "failed": 0}
        )
        counts[status] += 1
        if status == "failed":
            failures.append(entry)

    failures.sort(key=lambda e: str(e.get("timestamp") or ""), reverse=True)
    recent_failures = [
        {
            "trigger_id": str(entry.get("trigger_id") or ""),
            "event_type": str(entry.get("event_type") or ""),
            "correlation_id": entry.get("correlation_id"),
            "error_code": entry.get("error_code"),
            "error_message": str(entry.get("error_message") or ""),
        }
        for entry in failures[:_MAX_RECENT_FAILURES]
    ]

    jobs_by_state: dict[str, int] = {}
    for record in _load_event_jobs(project_root):
        state = str(record.get("state") or "")
        if state:
            jobs_by_state[state] = jobs_by_state.get(state, 0) + 1

    return {
        "by_trigger": by_trigger,
        "jobs_by_state": jobs_by_state,
        "recent_failures": recent_failures,
    }
