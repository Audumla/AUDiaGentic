"""Packet runner for MVP jobs."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs import control as job_control
from audiagentic.components.agent_jobs.profiles import load_profile
from audiagentic.components.agent_jobs.records import build_job_record
from audiagentic.components.agent_jobs.stages import execute_stage
from audiagentic.components.agent_jobs.state_machine import transition_and_persist
from audiagentic.components.providers.descriptors.registry import canonical_provider_ids
from audiagentic.foundation.contracts.canonical_ids import validate_ids
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)
from audiagentic.components.agent_jobs import jobs_store as store

StageExecutor = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None],
    dict[str, Any],
]
ProviderAdapter = Callable[[dict[str, Any]], dict[str, Any]]




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


def _stub_stage_executor(
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


def _should_stop_stage_loop(output: dict[str, Any]) -> bool:
    return output.get("next-stage-recommendation") in {"stop", "escalate"}


def _apply_pending_control(project_root: Path, job_id: str) -> dict[str, Any] | None:
    return job_control.apply_pending_job_control(project_root, job_id)


def _validate_provider_id(provider_id: str) -> None:
    issues = validate_ids([provider_id], canonical_provider_ids())
    if issues:
        raise AudiaGenticError(
            code="VAL-RUN-001",
            kind="agent-jobs",
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
    stage_executor: StageExecutor | None = None,
    stage_handler: StageExecutor | None = None,
    provider_adapter: ProviderAdapter | None = None,
    now_fn: Callable[[], str] | None = None,
) -> dict[str, Any]:
    if not provider_id:
        raise AudiaGenticError(
            code="VAL-RUN-002",
            kind="agent-jobs",
            message="provider-id is required",
            details={},
        )
    _validate_provider_id(provider_id)

    job_id = job_id or generate_job_id(project_root)
    timestamp = (now_fn or now_iso_z)()
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
    transition_and_persist(project_root, job_id, "running", now_fn=now_fn)

    handler = stage_executor or stage_handler or _stub_stage_executor
    try:
        profile = load_profile(workflow_profile, overrides=overrides)
        packet_ctx = {
            "project-id": project_id,
            "packet-id": packet_id,
            "provider-id": provider_id,
            "workflow-profile": workflow_profile,
            "job-id": job_id,
        }
        control = _apply_pending_control(project_root, job_id)
        if control and control.get("result") == "applied":
            return store.read_job_record(project_root, job_id)
        provider_result = (provider_adapter or _stub_provider)(packet_ctx)
        control = _apply_pending_control(project_root, job_id)
        if control and control.get("result") == "applied":
            return store.read_job_record(project_root, job_id)
        previous_output: dict[str, Any] | None = None

        for stage in profile["stages"]:
            control = _apply_pending_control(project_root, job_id)
            if control and control.get("result") == "applied":
                return store.read_job_record(project_root, job_id)
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

            control = _apply_pending_control(project_root, job_id)
            if control and control.get("result") == "applied":
                return store.read_job_record(project_root, job_id)

            if output.get("stage-result") == "failure":
                if stage.get("required", False):
                    transition_and_persist(project_root, job_id, "failed", now_fn=now_fn)
                    return store.read_job_record(project_root, job_id)
                if _should_stop_stage_loop(output):
                    break
                continue

            if _should_stop_stage_loop(output):
                break

        transition_and_persist(project_root, job_id, "completed", now_fn=now_fn)
        return store.read_job_record(project_root, job_id)
    except AudiaGenticError:
        try:
            transition_and_persist(project_root, job_id, "failed", now_fn=now_fn)
        except AudiaGenticError:
            logger.debug("failed to persist 'failed' transition", exc_info=True)
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            transition_and_persist(project_root, job_id, "failed", now_fn=now_fn)
        except AudiaGenticError:
            logger.debug("failed to persist 'failed' transition", exc_info=True)
        raise AudiaGenticError(
            code="INT-RUN-001",
            kind="agent-jobs",
            message="packet runner failed during stage execution",
            details={"job-id": job_id, "error": str(exc)},
        ) from exc
