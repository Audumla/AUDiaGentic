"""Prompt-to-job launch helpers."""
from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from audiagentic.execution.jobs.prompt_syntax import load_prompt_syntax, load_review_tag
from audiagentic.execution.jobs.prompt_templates import (
    load_prompt_context,
    load_prompt_template,
    render_prompt_template,
)
from audiagentic.execution.jobs.records import build_job_record
from audiagentic.execution.jobs.reviews import (
    build_review_bundle,
    build_review_report,
    persist_review_bundle,
    persist_review_report,
    reviewer_key_from_source,
    subject_from_target,
)
from audiagentic.execution.jobs.state_machine import TERMINAL_STATES
from audiagentic.foundation.config.provider_config import load_provider_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.providers.execution import execute_provider
from audiagentic.interoperability.providers.models import resolve_model_selection
from audiagentic.runtime.state import jobs_store as store


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def load_project_config(project_root: Path) -> dict[str, Any]:
    path = project_root / ".audiagentic" / "project.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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
    timestamp = (now_fn or _now_timestamp)()
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
    timestamp = (now_fn or _now_timestamp)()
    target = request["target"]
    provider_config = load_provider_config(project_root).get("providers", {})
    provider_id = request["source"].get("provider-id") or "local-openai"
    selection = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config.get(provider_id, {}),
        job_request={
            "model-id": request["source"].get("model-id"),
            "model-alias": request["source"].get("model-alias"),
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
    _write_atomic(prompt_launch_path(project_root, job_id), request)
    if request["target"]["kind"] == "adhoc":
        _write_atomic(subject_manifest_path(project_root, job_id), _build_launch_subject(request, job_id=job_id, now_fn=now_fn))
    return payload


def _resume_job_from_request(project_root: Path, request: dict[str, Any], *, now_fn=None) -> dict[str, Any]:
    job_id = request.get("existing-job-id") or request["target"].get("job-id")
    if not job_id:
        raise AudiaGenticError(
            code="JOB-VALIDATION-035",
            kind="validation",
            message="resume requires an existing job id",
            details={},
        )
    job = store.read_job_record(project_root, job_id)
    if job["state"] in TERMINAL_STATES:
        raise AudiaGenticError(
            code="JOB-BUSINESS-004",
            kind="business-rule",
            message="cannot resume a terminal job",
            details={"job-id": job_id, "state": job["state"]},
        )
    provider_config = load_provider_config(project_root).get("providers", {})
    provider_id = request["source"].get("provider-id") or job["provider-id"]
    selection = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config.get(provider_id, {}),
        job_request={
            "model-id": request["source"].get("model-id") or job.get("model-id"),
            "model-alias": request["source"].get("model-alias") or job.get("model-alias"),
        },
        catalog=None,
    )
    job["updated-at"] = (now_fn or _now_timestamp)()
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
    _write_atomic(prompt_launch_path(project_root, job_id), request)
    return job


def _launch_review_request(project_root: Path, request: dict[str, Any], *, now_fn=None) -> dict[str, Any]:
    job_id = _resolve_job_id(project_root, request, now_fn=now_fn)
    review_tag = load_review_tag(load_prompt_syntax(project_root))
    subject = subject_from_target(request["target"], existing_job_id=request.get("existing-job-id"))
    review_id = f"rvr_{request['prompt-id'].split('_', 1)[-1]}"
    reviewer = {
        "provider-id": request["source"].get("provider-id"),
        "surface": request["source"]["surface"],
        "session-id": request["source"].get("session-id"),
        "prompt-id": request["prompt-id"],
        "reviewer-key": reviewer_key_from_source(request["source"]),
    }
    provider_id = request["source"].get("provider-id")
    provider_config = load_provider_config(project_root).get("providers", {})
    provider_cfg = provider_config.get(provider_id or "", {})
    prompt_controls = request.get("prompt-controls", {})
    rendered_prompt = request["prompt-body"]
    template_name = prompt_controls.get("template") if isinstance(prompt_controls, dict) else None
    context_value = prompt_controls.get("context") if isinstance(prompt_controls, dict) else None
    resolved_context, context_path = load_prompt_context(project_root, context_value if isinstance(context_value, str) else None)
    if provider_id:
        template_text, template_path = load_prompt_template(
            project_root,
            tag=request["tag"],
            provider_id=provider_id,
            template_name=template_name if isinstance(template_name, str) and template_name else None,
        )
        if template_text:
            rendered_prompt = render_prompt_template(
                template_text,
                {
                    "id": prompt_controls.get("id") if isinstance(prompt_controls, dict) else None,
                    "context": resolved_context,
                    "output": prompt_controls.get("output") if isinstance(prompt_controls, dict) else None,
                    "template": template_name,
                    "provider": provider_id,
                    "tag": request["tag"],
                    "body": request["prompt-body"],
                    "subject": subject,
                    "project-root": str(project_root),
                    "template-path": str(template_path) if template_path else None,
                    "context-path": str(context_path) if context_path else None,
                },
            )
    prompt_for_criteria = request["prompt-body"].strip() or rendered_prompt.strip()
    criteria = [line.strip() for line in prompt_for_criteria.splitlines() if line.strip()]
    if not criteria:
        criteria = ["review the subject against the requested prompt"]
    report_payload: dict[str, Any] | None = None
    if provider_id and provider_cfg.get("access-mode") in {"cli", "external-configured", "none"}:
        try:
            provider_result = execute_provider(
                provider_id=provider_id,
                packet_ctx={
                    "provider-id": provider_id,
                    "job-id": job_id,
                    "packet-id": subject.get("job-id")
                    or subject.get("packet-id")
                    or subject.get("artifact-id")
                    or subject.get("adhoc-id")
                    or job_id,
                    "workflow-profile": request["workflow-profile"],
                    "working-root": str(project_root),
                    "prompt-body": rendered_prompt,
                    "prompt-controls": prompt_controls,
                    "stream-controls": request.get("stream-controls", {}),
                    "input-controls": request.get("input-controls", {}),
                },
                provider_cfg=provider_cfg,
            )
            output_text = str(provider_result.get("output") or "").strip()
            if output_text:
                try:
                    parsed = json.loads(output_text)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    findings = parsed.get("findings", [])
                    recommendation = parsed.get("recommendation", "pass-with-notes")
                    follow_up_actions = parsed.get("follow-up-actions", [])
                    if isinstance(findings, list) and isinstance(follow_up_actions, list) and isinstance(recommendation, str):
                        report_payload = build_review_report(
                            review_id=review_id,
                            subject=subject,
                            reviewer=reviewer,
                            criteria=criteria,
                            findings=findings,
                            recommendation=recommendation,
                            follow_up_actions=follow_up_actions,
                            created_at=(now_fn or _now_timestamp)(),
                        )
        except AudiaGenticError:
            report_payload = None
    report = report_payload or build_review_report(
        review_id=review_id,
        subject=subject,
        reviewer=reviewer,
        criteria=criteria,
        findings=[],
        recommendation="pass-with-notes",
        follow_up_actions=[],
        created_at=(now_fn or _now_timestamp)(),
    )
    bundle = build_review_bundle(
        review_bundle_id=f"rvb_{review_id.split('_', 1)[-1]}",
        subject=subject,
        required_reviews=request.get("review-policy", {}).get("required-reviews", 1),
        aggregation_rule=request.get("review-policy", {}).get("aggregation-rule", "all-pass"),
        require_distinct_reviewers=request.get("review-policy", {}).get("require-distinct-reviewers", True),
        reports=[
            {
                "review-id": report["review-id"],
                "reviewer-key": report["reviewer"]["reviewer-key"],
                "recommendation": report["recommendation"],
            }
        ],
        updated_at=(now_fn or _now_timestamp)(),
    )
    _write_atomic(prompt_launch_path(project_root, job_id), request)
    persist_review_report(project_root, job_id, report)
    persist_review_bundle(project_root, job_id, bundle)
    if request.get("existing-job-id") or request["target"]["kind"] == "job":
        try:
            job = store.read_job_record(project_root, job_id)
        except AudiaGenticError:
            job = None
        if job is not None:
            job["review-bundle-id"] = bundle["review-bundle-id"]
            store.write_job_record(project_root, job)
    return {
        "job-id": job_id,
        "review-id": report["review-id"],
        "review-bundle-id": bundle["review-bundle-id"],
        "decision": bundle["decision"],
        "status": bundle["status"],
    }


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
        return {"status": "ok", **_launch_review_request(project_root, request, now_fn=now_fn)}
    if request.get("existing-job-id") or request["target"]["kind"] == "job":
        job = _resume_job_from_request(project_root, request, now_fn=now_fn)
        return {"status": "resumed", "job-id": job["job-id"], "job": job}
    job = _build_job_from_request(project_root, request, now_fn=now_fn)
    return {"status": "created", "job-id": job["job-id"], "job": job}
