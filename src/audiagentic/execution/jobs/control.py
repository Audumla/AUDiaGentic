"""Job control and cancellation helpers.

Provides job control request building, persistence, and application logic.
Supports dependency injection for testability while maintaining backward
compatibility with global store access.

Key functions:
- build_job_control_request: Create control request payload
- request_job_control: Submit control request with state validation
- apply_pending_job_control: Apply pending control requests

Dependency injection:
- Functions accept optional `store` parameter for test isolation
- Defaults to global jobs_store for backward compatibility
- Use `from audiagentic.runtime.state import jobs_store` for explicit injection
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.execution.jobs.state_machine import TERMINAL_STATES, transition_and_persist
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.state import jobs_store as _default_store

# Type alias for store interface
JobStoreInterface = Callable[[Path, str], dict[str, Any]]


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _control_path(project_root: Path, job_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id / "job-control.json"


def _control_events_path(project_root: Path, job_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id / "control-events.ndjson"


def _write_atomic(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return path


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def build_job_control_request(
    *,
    job_id: str,
    project_id: str,
    requested_action: str,
    requested_by: str,
    reason: str,
    requested_at: str | None = None,
) -> dict[str, Any]:
    if requested_action not in {"cancel", "stop", "kill"}:
        raise AudiaGenticError(
            code="JOB-VALIDATION-040",
            kind="validation",
            message="unsupported job control action",
            details={"requested-action": requested_action},
        )
    payload = {
        "contract-version": "v1",
        "job-id": job_id,
        "project-id": project_id,
        "requested-action": requested_action,
        "requested-by": requested_by,
        "requested-at": requested_at or _now_timestamp(),
        "reason": reason,
        "result": "pending",
        "applied-at": None,
    }
    return payload


def read_job_control(project_root: Path, job_id: str) -> dict[str, Any] | None:
    path = _control_path(project_root, job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="JOB-IO-004",
            kind="io",
            message="failed to read job control record",
            details={"job-id": job_id, "error": str(exc)},
        ) from exc


def write_job_control(project_root: Path, payload: dict[str, Any]) -> Path:
    return _write_atomic(_control_path(project_root, payload["job-id"]), payload)


def request_job_control(
    project_root: Path,
    payload: dict[str, Any],
    store: JobStoreInterface = _default_store,
) -> dict[str, Any]:
    """Submit job control request with state validation.

    Checks job state and applies control request appropriately:
    - Terminal states: Ignore request, mark as ignored
    - Ready/awaiting-approval: Transition to cancelled immediately
    - Other states: Mark request as pending for later application

    Args:
        project_root: Project root directory path
        payload: Control request payload with job-id, action, etc.
        store: Job store interface for reading job records (default: global jobs_store)

    Returns:
        Updated payload with result and applied-at fields

    Example:
        >>> payload = build_job_control_request(job_id="job-001", ...)
        >>> result = request_job_control(project_root, payload)
        >>> print(result["result"])  # "applied", "pending", or "ignored"
    """
    job = store.read_job_record(project_root, payload["job-id"])
    if job["state"] in TERMINAL_STATES:
        payload = dict(payload)
        payload["result"] = "ignored"
        payload["applied-at"] = _now_timestamp()
        write_job_control(project_root, payload)
        _append_event(
            _control_events_path(project_root, payload["job-id"]),
            {
                "event-type": "job-control-ignored",
                "job-id": payload["job-id"],
                "project-id": payload["project-id"],
                "requested-action": payload["requested-action"],
                "requested-by": payload["requested-by"],
                "requested-at": payload["requested-at"],
                "applied-at": payload["applied-at"],
                "reason": "job already terminal",
            },
        )
        return payload

    payload = dict(payload)
    if job["state"] in {"ready", "awaiting-approval"}:
        transition_and_persist(project_root, payload["job-id"], "cancelled")
        payload["result"] = "applied"
        payload["applied-at"] = _now_timestamp()
    else:
        payload["result"] = "pending"
        payload["applied-at"] = None
    write_job_control(project_root, payload)
    _append_event(
        _control_events_path(project_root, payload["job-id"]),
        {
            "event-type": "job-control-requested",
            "job-id": payload["job-id"],
            "project-id": payload["project-id"],
            "requested-action": payload["requested-action"],
            "requested-by": payload["requested-by"],
            "requested-at": payload["requested-at"],
            "reason": payload["reason"],
            "result": payload["result"],
            "applied-at": payload["applied-at"],
        },
    )
    return payload


def apply_pending_job_control(
    project_root: Path,
    job_id: str,
    store: JobStoreInterface = _default_store,
) -> dict[str, Any] | None:
    """Apply pending job control request.

    Checks for pending control requests and applies them based on current job state:
    - No control request: Return None
    - Already applied/ignored: Return existing control record
    - Terminal state: Mark as ignored
    - Active state: Transition to cancelled and mark as applied

    Args:
        project_root: Project root directory path
        job_id: Job identifier
        store: Job store interface for reading job records (default: global jobs_store)

    Returns:
        Updated control record or None if no control request exists

    Example:
        >>> control = apply_pending_job_control(project_root, "job-001")
        >>> if control and control["result"] == "applied":
        ...     print("Job cancelled")
    """
    control = read_job_control(project_root, job_id)
    if control is None:
        return None
    if control.get("result") != "pending":
        return control
    if control.get("requested-action") not in {"cancel", "stop", "kill"}:
        return control
    job = store.read_job_record(project_root, job_id)
    if job["state"] in TERMINAL_STATES:
        control["result"] = "ignored"
        control["applied-at"] = _now_timestamp()
        write_job_control(project_root, control)
        _append_event(
            _control_events_path(project_root, job_id),
            {
                "event-type": "job-control-ignored",
                "job-id": job_id,
                "project-id": control["project-id"],
                "requested-action": control["requested-action"],
                "requested-by": control["requested-by"],
                "requested-at": control["requested-at"],
                "applied-at": control["applied-at"],
                "reason": "job already terminal",
            },
        )
        return control
    transition_and_persist(project_root, job_id, "cancelled")
    control["result"] = "applied"
    control["applied-at"] = _now_timestamp()
    write_job_control(project_root, control)
    _append_event(
        _control_events_path(project_root, job_id),
        {
            "event-type": "job-control-applied",
            "job-id": job_id,
            "project-id": control["project-id"],
            "requested-action": control["requested-action"],
            "requested-by": control["requested-by"],
            "requested-at": control["requested-at"],
            "applied-at": control["applied-at"],
            "result": control["result"],
        },
    )
    return control
