"""Packet runner for MVP jobs."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from audiagentic.contracts.canonical_ids import CANONICAL_PROVIDER_IDS, validate_ids
from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.jobs import store
from audiagentic.jobs.profiles import load_profile
from audiagentic.jobs.records import build_job_record
from audiagentic.jobs.state_machine import transition_and_persist
from audiagentic.jobs.stages import StageHandler, execute_stage

ProviderAdapter = Callable[[dict[str, Any]], dict[str, Any]]


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jobs_root(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs"


def generate_job_id(project_root: Path) -> str:
    date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    pattern = re.compile(rf"^job_{date_prefix}_(\d{{4}})$")
    root = _jobs_root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    sequence = 0
    for path in root.iterdir():
        if not path.is_dir():
            continue
        match = pattern.match(path.name)
        if match:
            sequence = max(sequence, int(match.group(1)))
    return f"job_{date_prefix}_{sequence + 1:04d}"


def _stub_provider(packet_ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider-id": packet_ctx.get("provider-id"),
        "status": "stubbed",
        "output": "stub-response",
    }


def _stub_stage_handler(
    job_record: dict[str, Any],
    stage: dict[str, Any],
    packet_ctx: dict[str, Any],
    previous_output: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "stage-result": "success",
        "artifacts": [],
        "next-stage-recommendation": "continue",
        "warnings": [],
        "stage-id": stage["id"],
    }


def _validate_provider_id(provider_id: str) -> None:
    issues = validate_ids([provider_id], CANONICAL_PROVIDER_IDS)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-015",
            kind="validation",
            message="provider-id is not canonical",
            details={"issues": issues},
        )


def run_packet(
    project_root: Path,
    *,
    packet_id: str,
    project_id: str,
    provider_id: str,
    workflow_profile: str,
    job_id: str | None = None,
    overrides: dict[str, Any] | None = None,
    stage_handler: StageHandler | None = None,
    provider_adapter: ProviderAdapter | None = None,
    now_fn: Callable[[], str] | None = None,
) -> dict[str, Any]:
    if not provider_id:
        raise AudiaGenticError(
            code="JOB-VALIDATION-016",
            kind="validation",
            message="provider-id is required",
            details={},
        )
    _validate_provider_id(provider_id)

    job_id = job_id or generate_job_id(project_root)
    timestamp = (now_fn or _now_timestamp)()
    record = build_job_record(
        job_id=job_id,
        packet_id=packet_id,
        project_id=project_id,
        provider_id=provider_id,
        workflow_profile=workflow_profile,
        state="created",
        created_at=timestamp,
        updated_at=timestamp,
    )
    store.write_job_record(project_root, record)
    transition_and_persist(project_root, job_id, "ready", now_fn=now_fn)

    profile = load_profile(workflow_profile, overrides=overrides)
    packet_ctx = {
        "project-id": project_id,
        "packet-id": packet_id,
        "provider-id": provider_id,
        "workflow-profile": workflow_profile,
    }
    provider_result = (provider_adapter or _stub_provider)(packet_ctx)

    handler = stage_handler or _stub_stage_handler
    previous_output: dict[str, Any] | None = None
    transition_and_persist(project_root, job_id, "running", now_fn=now_fn)
    for stage in profile["stages"]:
        if stage.get("enabled") is False and not stage.get("required", False):
            continue
        stage_input = {"provider-result": provider_result}
        envelope = execute_stage(
            project_root,
            job_record=record,
            stage=stage,
            packet_ctx=packet_ctx,
            handler=handler,
            previous_output=previous_output | stage_input if previous_output else stage_input,
        )
        output = envelope["output"]
        previous_output = output
        if output.get("stage-result") == "failure":
            if stage.get("required", False):
                transition_and_persist(project_root, job_id, "failed", now_fn=now_fn)
                return store.read_job_record(project_root, job_id)
            continue
    transition_and_persist(project_root, job_id, "completed", now_fn=now_fn)
    return store.read_job_record(project_root, job_id)
