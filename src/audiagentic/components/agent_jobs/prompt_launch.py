"""Prompt-to-job launch helpers."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs import jobs_store as store
from audiagentic.components.agent_jobs.paths import job_timeline_path
from audiagentic.components.agent_jobs.prompt_syntax import (
    load_prompt_syntax,
    load_review_tag,
)
from audiagentic.components.agent_jobs.records import build_job_record
from audiagentic.components.agent_jobs.state_machine import TERMINAL_STATES
from audiagentic.components.providers.services.models import resolve_model_selection
from audiagentic.components.providers.services.provider_config import (
    is_provider_enabled,
    load_provider_config,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, load_yaml_file
from audiagentic.foundation.logging.context import get_correlation_id, new_correlation_id
from audiagentic.foundation.observability import record_timeline_event
from audiagentic.foundation.time import now_iso_z


def load_project_config(project_root: Path) -> dict[str, Any]:
    path = project_root / ".audiagentic" / "config" / "project.yaml"
    return load_yaml_file(path)


def _resolve_agent_provider_model(
    project_root: Path,
    request: dict[str, Any],
) -> tuple[str, str | None, str | None]:
    """Resolve provider_id, model_id, model_alias from agent profile or request.

    Precedence:
      1. agent-profile-id in request -> resolve profile -> override provider/model
      2. Explicit provider-id / model-id in request source
      3. Default agent profile
      4. Fallback to local-openai (backward compat)

    Returns (provider_id, model_id, model_alias).
    """
    source = request.get("source", {})
    explicit_provider = source.get("provider-id")
    explicit_model = source.get("model-id")
    explicit_alias = source.get("model-alias")

    agent_profile_id = request.get("agent-profile-id")
    if agent_profile_id:
        from audiagentic.components.agents.agents_api import resolve_profile
        resolved = resolve_profile(project_root, agent_profile_id)
        provider_id = resolved["provider_id"]
        if not is_provider_enabled(project_root, provider_id):
            raise AudiaGenticError(
                code="CON-AGJ-002",
                kind="agent-jobs",
                message="agent profile references a disabled provider",
                details={
                    "profile_id": agent_profile_id,
                    "provider_id": provider_id,
                },
            )
        return provider_id, resolved.get("model_id"), resolved.get("model_alias")

    if explicit_provider or explicit_model:
        return explicit_provider or "local-openai", explicit_model, explicit_alias

    try:
        from audiagentic.components.agents.agents_api import resolve_default_profile
        resolved = resolve_default_profile(project_root)
        provider_id = resolved["provider_id"]
        if not is_provider_enabled(project_root, provider_id):
            raise AudiaGenticError(
                code="CON-AGJ-002",
                kind="agent-jobs",
                message="default agent profile references a disabled provider",
                details={
                    "profile_id": resolved["profile_id"],
                    "provider_id": provider_id,
                },
            )
        return provider_id, resolved.get("model_id"), resolved.get("model_alias")
    except AudiaGenticError as exc:
        if exc.code == "RES-AGP-003":
            raise AudiaGenticError(
                code="CON-AGJ-001",
                kind="agent-jobs",
                message="no default agent profile and no explicit provider/model in request",
                details={},
            ) from exc
        raise


def _apply_launch_defaults(project_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(request)
    prompt_launch = load_project_config(project_root).get("prompt-launch", {})
    if isinstance(prompt_launch, dict):
        defaults = {
            "review-policy": prompt_launch.get("default-review-policy"),
            "stream-controls": prompt_launch.get("default-stream-controls"),
            "input-controls": prompt_launch.get("default-input-controls"),
        }
        for key, value in defaults.items():
            if key not in merged and isinstance(value, dict):
                merged[key] = deepcopy(value)
    return merged


def prompt_launch_path(project_root: Path, job_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id / "launch-request.json"


def subject_manifest_path(project_root: Path, job_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id / "subject.json"


def generate_subject_id(*, now_fn=None) -> str:
    timestamp = (now_fn or now_iso_z)()
    compact = timestamp.replace("-", "").replace(":", "").replace("Z", "").replace("T", "_")
    return f"adh_{compact[:15]}"


def _resolve_job_id(project_root: Path, request: dict[str, Any], now_fn=None) -> str:
    existing_job_id = request.get("existing-job-id")
    target = request["target"]
    if existing_job_id:
        return existing_job_id
    if target["kind"] == "job":
        return target["job-id"]
    date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    root = project_root / ".audiagentic" / "runtime" / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    existing = 0
    prefix = f"job_{date_prefix}_"
    for path in root.iterdir():
        if path.is_dir() and path.name.startswith(prefix):
            suffix = path.name[len(prefix) :]
            if suffix.isdigit():
                existing = max(existing, int(suffix))
    return f"job_{date_prefix}_{existing + 1:04d}"


def _build_launch_subject(request: dict[str, Any], *, job_id: str, now_fn=None) -> dict[str, Any]:
    target = request["target"]
    if target["kind"] == "adhoc":
        return {
            "contract-version": "v1",
            "subject-id": target.get("adhoc-id") or generate_subject_id(now_fn=now_fn),
            "kind": "adhoc",
            "summary": request["prompt-body"].strip() or "Ad hoc prompt launch",
        }
    return {
        "contract-version": "v1",
        "subject-id": job_id,
        "kind": target["kind"],
        "summary": request["prompt-body"].strip()[:240] or request["tag"],
    }


def _build_job_from_request(
    project_root: Path,
    request: dict[str, Any],
    *,
    now_fn=None,
) -> dict[str, Any]:
    job_id = _resolve_job_id(project_root, request, now_fn=now_fn)
    timestamp = (now_fn or now_iso_z)()
    target = request["target"]
    provider_config = load_provider_config(project_root).get("providers", {})
    provider_id, resolved_model, resolved_alias = _resolve_agent_provider_model(project_root, request)
    selection = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config.get(provider_id, {}),
        job_request={
            "model-id": resolved_model or request["source"].get("model-id"),
            "model-alias": resolved_alias or request["source"].get("model-alias"),
        },
        catalog=None,
    )
    packet_id = (
        target.get("packet-id")
        or target.get("job-id")
        or target.get("artifact-id")
        or target.get("artifact-path")
        or "adhoc"
    )
    launch_source = {
        "prompt-id": request["prompt-id"],
        "surface": request["source"]["surface"],
        "session-id": request["source"].get("session-id"),
    }
    payload = build_job_record(
        job_id=job_id,
        packet_id=str(packet_id),
        project_id=load_project_config(project_root).get("project-id", "my-project"),
        provider_id=provider_id,
        workflow_profile=request["workflow-profile"],
        state="ready",
        created_at=timestamp,
        updated_at=timestamp,
        model_id=selection.get("model-id"),
        model_alias=selection.get("model-alias"),
        default_model=selection.get("default-model"),
        launch_source=launch_source,
        launch_tag=request["tag"],
        launch_target=request["target"],
        review_policy=request.get("review-policy"),
        review_bundle_id=None,
    )
    store.write_job_record(project_root, payload)
    atomic_write_json(prompt_launch_path(project_root, job_id), request)
    if request["target"]["kind"] == "adhoc":
        atomic_write_json(subject_manifest_path(project_root, job_id), _build_launch_subject(request, job_id=job_id, now_fn=now_fn))
    return payload


def _resume_job_from_request(project_root: Path, request: dict[str, Any], *, now_fn=None) -> dict[str, Any]:
    job_id = request.get("existing-job-id") or request["target"].get("job-id")
    if not job_id:
        raise AudiaGenticError(
            code="VAL-LAUNCH-001",
            kind="agent-jobs",
            message="resume requires an existing job id",
            details={},
        )
    job = store.read_job_record(project_root, job_id)
    if job["state"] in TERMINAL_STATES:
        raise AudiaGenticError(
            code="CON-LAUNCH-001",
            kind="agent-jobs",
            message="cannot resume a terminal job",
            details={"job-id": job_id, "state": job["state"]},
        )
    provider_config = load_provider_config(project_root).get("providers", {})
    provider_id, resolved_model, resolved_alias = _resolve_agent_provider_model(project_root, request)
    if not provider_id:
        provider_id = job["provider-id"]
    selection = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config.get(provider_id, {}),
        job_request={
            "model-id": resolved_model or request["source"].get("model-id") or job.get("model-id"),
            "model-alias": resolved_alias or request["source"].get("model-alias") or job.get("model-alias"),
        },
        catalog=None,
    )
    job["updated-at"] = (now_fn or now_iso_z)()
    launch_source = {
        "prompt-id": request["prompt-id"],
        "surface": request["source"]["surface"],
        "session-id": request["source"].get("session-id"),
    }
    job["launch-source"] = launch_source
    job["launch-tag"] = request["tag"]
    job["launch-target"] = request["target"]
    if request["review-policy"] is not None:
        job["review-policy"] = request["review-policy"]
    if request["source"].get("model-id") is not None:
        job["model-id"] = selection["model-id"]
    if request["source"].get("model-alias") is not None:
        job["model-alias"] = selection.get("model-alias")
    if selection.get("default-model") is not None:
        job["default-model"] = selection.get("default-model")
    store.write_job_record(project_root, job)
    atomic_write_json(prompt_launch_path(project_root, job_id), request)
    return job


def launch_prompt_request(
    project_root: Path,
    request: dict[str, Any],
    *,
    now_fn=None,
) -> dict[str, Any]:
    request = _apply_launch_defaults(project_root, request)
    review_tag = load_review_tag(load_prompt_syntax(project_root))
    prompt_launch = load_project_config(project_root).get("prompt-launch", {})
    if (
        request["target"]["kind"] == "adhoc"
        and request.get("target-origin") != "default"
        and not prompt_launch.get("allow-adhoc-target", False)
    ):
        return {
            "status": "not-enabled",
            "reason": "adhoc target disabled",
            "prompt-id": request["prompt-id"],
        }
    if request["tag"] == review_tag:
        from audiagentic.components.agent_jobs.review_launch import launch_review_request

        return {"status": "ok", **launch_review_request(project_root, request, now_fn=now_fn)}
    if request.get("existing-job-id") or request["target"]["kind"] == "job":
        job = _resume_job_from_request(project_root, request, now_fn=now_fn)
        return {"status": "resumed", "job-id": job["job-id"], "job": job}
    job = _build_job_from_request(project_root, request, now_fn=now_fn)
    return {"status": "created", "job-id": job["job-id"], "job": job}


def build_job_from_event(
    project_root: Path,
    *,
    event_type: str,
    trigger_config: dict[str, Any],
    envelope: dict[str, Any],
    prompt_body: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable job record from an event trigger.

    Populates event-source provenance from the event envelope, sets
    launch-source.surface to 'event', writes the job record and launch
    request, and records the first timeline entry (job.created).

    Parameters
    ----------
    project_root:
        Root of the AUDiaGentic project.
    event_type:
        Type of the triggering event (e.g. 'planning.item.created').
    trigger_config:
        Validated trigger configuration dict (from TriggerConfig or raw).
    envelope:
        EventEnvelope payload as a dict. Provides occurred_at, source_kind,
        source_id, and metadata fields.
    prompt_body:
        Rendered prompt body to associate with this job.
    job_id:
        Explicit job id; auto-generated if not provided.

    Returns
    -------
    dict containing the persisted job record.
    """
    timestamp = now_iso_z()

    # Resolve correlation_id from envelope metadata or generate one
    metadata = envelope.get("metadata", {}) or {}
    correlation_id = (
        metadata.get("correlation-id")
        or metadata.get("correlation_id")
        or get_correlation_id()
        or new_correlation_id()
    )

    # Extract subject from envelope metadata
    subject = metadata.get("subject")
    if isinstance(subject, dict):
        event_subject = {
            "kind": subject.get("kind", ""),
            "id": subject.get("id", ""),
        }
    elif subject is None:
        event_subject = None
    else:
        event_subject = {"kind": "", "id": str(subject)}

    # Build event-source block from envelope (additive provenance, no raw payload)
    event_source = {
        "event-type": event_type,
        "trigger-id": trigger_config.get("trigger-id", ""),
        "correlation-id": correlation_id,
        "subject": event_subject,
        "source-component": envelope.get("source-kind", ""),
        "occurred-at": envelope.get("occurred-at"),
    }

    # Resolve provider/model selection
    provider_config = load_provider_config(project_root).get("providers", {})
    project_cfg = load_project_config(project_root)
    provider_id, resolved_model, resolved_alias = _resolve_agent_provider_model(
        project_root,
        {
            "agent-profile-id": trigger_config.get("agent-profile-id"),
            "source": {},
        },
    )
    selection = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config.get(provider_id, {}),
        job_request={
            "model-id": resolved_model,
            "model-alias": resolved_alias,
        },
        catalog=None,
    )

    # Resolve workflow profile
    workflow_profile = trigger_config.get("workflow-profile") or "standard"

    # Auto-generate job id if not provided
    if not job_id:
        date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
        root = project_root / ".audiagentic" / "runtime" / "jobs"
        root.mkdir(parents=True, exist_ok=True)
        existing = 0
        prefix = f"job_{date_prefix}_"
        for path in root.iterdir():
            if path.is_dir() and path.name.startswith(prefix):
                suffix = path.name[len(prefix):]
                if suffix.isdigit():
                    existing = max(existing, int(suffix))
        job_id = f"job_{date_prefix}_{existing + 1:04d}"

    # Build trigger-specific target
    target = trigger_config.get("target") or {"kind": "adhoc"}
    packet_id = (
        target.get("packet-id")
        or target.get("job-id")
        or target.get("artifact-id")
        or target.get("artifact-path")
        or "adhoc"
    )

    # Build launch-source with surface='event'
    launch_source = {
        "prompt-id": envelope.get("event-id", ""),
        "surface": "event",
        "session-id": None,
    }

    # Build and persist the job record
    payload = build_job_record(
        job_id=job_id,
        packet_id=str(packet_id),
        project_id=project_cfg.get("project-id", "my-project"),
        provider_id=provider_id,
        workflow_profile=workflow_profile,
        state="created",
        created_at=timestamp,
        updated_at=timestamp,
        model_id=selection.get("model-id"),
        model_alias=selection.get("model-alias"),
        default_model=selection.get("default-model"),
        launch_source=launch_source,
        launch_target=target,
        event_source=event_source,
    )

    store.write_job_record(project_root, payload)

    # Write minimal launch request for the event-triggered job
    launch_request = {
        "prompt-id": envelope.get("event-id", ""),
        "prompt-body": prompt_body,
        "source": {
            "surface": "event",
            "provider-id": provider_id,
        },
        "target": target,
        "workflow-profile": workflow_profile,
        "tag": "event-triggered",
    }
    atomic_write_json(prompt_launch_path(project_root, job_id), launch_request)

    # Record the first timeline entry via EDJ07 shared helper
    record_timeline_event(
        job_timeline_path(project_root, job_id),
        component="agent-jobs",
        resource_kind="job",
        resource_id=job_id,
        event="job.created",
        state="created",
        attributes={
            "correlation_id": correlation_id,
            "trigger_id": event_source["trigger-id"],
            "event_type": event_type,
            "surface": "event",
        },
        timestamp=timestamp,
        correlation_id=correlation_id,
    )

    return payload
