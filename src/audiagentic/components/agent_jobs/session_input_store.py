"""Live session input capture helpers.

Provides session input building and persistence with dependency injection support.
Supports test isolation while maintaining backward compatibility with global store access.

Key functions:
- build_session_input_record: Create session input record payload
- persist_session_input: Persist record to NDJSON files
- build_and_persist_session_input: Combined build and persist operation

Session input is attached to canonical Work and is persisted as an idempotent
Work input message through the public Work API.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

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


def persist_session_input(project_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    work_id = record.get("work-id")
    if not isinstance(work_id, str) or not work_id:
        raise AudiaGenticError(
            code="VAL-SESSION-001",
            kind="state-store",
            message="session input record requires a canonical Work id",
            details={},
        )
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
) -> dict[str, Any]:
    """Build and persist a session input record.

    Args:
        project_root: Project root directory path
        job_id: Job identifier
        prompt_id: Optional prompt identifier
        provider_id: Optional provider identifier
        surface: Input surface (e.g., "cli", "api", "ide")
        stage: Processing stage (e.g., "planning", "execution")
        event_kind: Event kind (e.g., "user.input", "system.response")
        message: Input message content
        timestamp: Optional ISO timestamp (defaults to current UTC time)
        details: Optional additional details dict

    Returns:
        Built and persisted session input record

        Session input is always attached to canonical Work.
    """
    if not work_id:
        raise AudiaGenticError(
            code="VAL-SESSION-002",
            kind="state-store",
            message="session input requires a canonical Work id",
            details={"job-id": job_id},
        )

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
