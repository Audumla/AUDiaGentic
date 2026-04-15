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
- Use `from audiagentic.runtime.state import jobs_store` for explicit injection
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.state import jobs_store as _default_store

# Type alias for job store interface
JobStoreInterface = Callable[[Path, str], dict[str, Any]]


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _job_runtime_root(project_root: Path, job_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id


def session_input_path(project_root: Path, job_id: str) -> Path:
    return _job_runtime_root(project_root, job_id) / "input.ndjson"


def session_input_events_path(project_root: Path, job_id: str) -> Path:
    return _job_runtime_root(project_root, job_id) / "input-events.ndjson"


def session_stdin_log_path(project_root: Path, job_id: str) -> Path:
    return _job_runtime_root(project_root, job_id) / "stdin.log"


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
        "timestamp": timestamp or _now_timestamp(),
    }
    if details is not None:
        payload["details"] = details
    return payload


def _append_ndjson(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


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
            code="JOB-VALIDATION-041",
            kind="validation",
            message="session input record requires a job id",
            details={},
        )
    _append_ndjson(session_input_path(project_root, record["job-id"]), record)
    _append_ndjson(session_input_events_path(project_root, record["job-id"]), record)
    message = record.get("message")
    if isinstance(message, str) and message:
        _append_text(session_stdin_log_path(project_root, record["job-id"]), message)
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
    job_store: JobStoreInterface = _default_store.read_job_record,
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
        job_store: Optional job store function for reading job records (defaults to global store)

    Returns:
        Built and persisted session input record

    Note:
        For test isolation, pass explicit job_store:
        `build_and_persist_session_input(..., job_store=mock_store.read_job_record)`
    """
    if provider_id is None:
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
    return persist_session_input(project_root, record)
