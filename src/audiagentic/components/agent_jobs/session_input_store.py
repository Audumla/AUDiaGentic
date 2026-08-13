"""Live session input capture helpers.

Provides session input building and persistence with dependency injection support.
Supports test isolation while maintaining backward compatibility with global store access.

Key functions:
- build_session_input_record: Create session input record payload
- persist_session_input: Persist record to NDJSON files
- build_and_persist_session_input: Combined build and persist operation

Dependency injection:
- Functions accept optional `job_store` parameter for test isolation
- Defaults to global jobs_store for backward compatibility
- Use `from audiagentic.components.agent_jobs import jobs_store` for explicit injection
"""

from __future__ import annotations

import logging
import os

# Type alias for job store interface
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs.paths import (
    job_input_events_path,
    job_input_path,
    job_stdin_log_path,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_ndjson
from audiagentic.foundation.time import now_iso_z

JobStoreInterface = Callable[[Path, str], dict[str, Any]]

logger = logging.getLogger(__name__)


def build_session_input_record(
    *,
    job_id: str,
    prompt_id: str | None,
    provider_id: str | None,
    surface: str,
    stage: str,
    event_kind: str,
    message: str,
    timestamp: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract-version": "v1",
        "job-id": job_id,
        "prompt-id": prompt_id,
        "provider-id": provider_id,
        "surface": surface,
        "stage": stage,
        "event-kind": event_kind,
        "message": message,
        "timestamp": timestamp or now_iso_z(),
    }
    if details is not None:
        payload["details"] = details
    return payload


def _append_ndjson(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_ndjson(path, [payload], append=True)


def _append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def persist_session_input(project_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("job-id"):
        raise AudiaGenticError(
            code="VAL-SESSION-001",
            kind="state-store",
            message="session input record requires a job id",
            details={},
        )
    work_id = record.get("work-id")
    if isinstance(work_id, str) and work_id:
        from audiagentic.components.agents.work.work_api import add_message

        message_id = record.get("message-id") or (
            f"session-input:{record.get('event-kind', 'input')}:{record['timestamp']}"
        )
        add_message(
            project_root,
            work_id,
            message_id=message_id,
            text=record.get("message", ""),
            inputs={
                "event-kind": record.get("event-kind"),
                "surface": record.get("surface"),
                "stage": record.get("stage"),
                **dict(record.get("details") or {}),
            },
        )
        return record
    _append_ndjson(job_input_path(project_root, record["job-id"]), record)
    _append_ndjson(job_input_events_path(project_root, record["job-id"]), record)
    message = record.get("message")
    if isinstance(message, str) and message:
        _append_text(job_stdin_log_path(project_root, record["job-id"]), message)
    return record


def build_and_persist_session_input(
    project_root: Path,
    *,
    job_id: str,
    prompt_id: str | None,
    provider_id: str | None,
    surface: str,
    stage: str,
    event_kind: str,
    message: str,
    timestamp: str | None = None,
    details: dict[str, Any] | None = None,
    work_id: str | None = None,
    job_store: JobStoreInterface | None = None,
) -> dict[str, Any]:
    """Build and persist a session input record.

    Args:
        project_root: Project root directory path
        job_id: Job identifier
        prompt_id: Optional prompt identifier
        provider_id: Optional provider identifier (falls back to job record if not provided)
        surface: Input surface (e.g., "cli", "api", "ide")
        stage: Processing stage (e.g., "planning", "execution")
        event_kind: Event kind (e.g., "user.input", "system.response")
        message: Input message content
        timestamp: Optional ISO timestamp (defaults to current UTC time)
        details: Optional additional details dict
        job_store: Optional job store function for reading legacy job records. It is
            resolved lazily only for the no-Work compatibility path.

    Returns:
        Built and persisted session input record

    Note:
        For test isolation, pass explicit job_store:
        `build_and_persist_session_input(..., job_store=mock_store.read_job_record)`
    """
    if provider_id is None and not work_id:
        if job_store is None:
            from audiagentic.components.agent_jobs.jobs_store import read_job_record

            job_store = read_job_record
        job = job_store(project_root, job_id)
        provider_id = job.get("provider-id")

    record = build_session_input_record(
        job_id=job_id,
        prompt_id=prompt_id,
        provider_id=provider_id,
        surface=surface,
        stage=stage,
        event_kind=event_kind,
        message=message,
        timestamp=timestamp,
        details=details,
    )
    if work_id:
        record["work-id"] = work_id
    return persist_session_input(project_root, record)
