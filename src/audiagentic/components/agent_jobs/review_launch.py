"""Review-request launch pipeline.

Extracted from ``prompt_launch.py``: the review tag drives a distinct pipeline
(template render -> provider execution -> JSON parse -> review report/bundle ->
persistence) that does not share state with job create/resume. Kept in its own
module and decomposed into stage helpers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs.prompt_templates import (
    load_prompt_context,
    load_prompt_template,
    render_prompt_template,
)
from audiagentic.components.agent_jobs.reviews import (
    build_review_bundle,
    build_review_report,
    persist_review_bundle,
    persist_review_report,
    reviewer_key_from_source,
    subject_from_target,
)
from audiagentic.components.providers.services.execution import execute_provider
from audiagentic.components.providers.services.provider_config import load_provider_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_iso_z


def _render_review_prompt(
    project_root: Path,
    request: dict[str, Any],
    *,
    provider_id: str | None,
    subject: dict[str, Any],
) -> str:
    """Resolve the review template/context and render the reviewer prompt."""
    prompt_controls = request.get("prompt-controls", {})
    rendered_prompt = request["prompt-body"]
    template_name = prompt_controls.get("template") if isinstance(prompt_controls, dict) else None
    context_value = prompt_controls.get("context") if isinstance(prompt_controls, dict) else None
    resolved_context, context_path = load_prompt_context(
        project_root, context_value if isinstance(context_value, str) else None
    )
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
    return rendered_prompt


def _execute_and_parse_review(
    project_root: Path,
    request: dict[str, Any],
    *,
    provider_id: str | None,
    provider_cfg: dict[str, Any],
    job_id: str,
    subject: dict[str, Any],
    review_id: str,
    reviewer: dict[str, Any],
    criteria: list[str],
    rendered_prompt: str,
    now_fn=None,
) -> dict[str, Any] | None:
    """Run the reviewer provider and parse its output into a review report.

    Returns ``None`` if the provider is not eligible/available or its output
    cannot be parsed into a well-formed report.
    """
    if not (provider_id and provider_cfg.get("access-mode") in {"cli", "external-configured", "none"}):
        return None
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
                "prompt-controls": request.get("prompt-controls", {}),
                "stream-controls": request.get("stream-controls", {}),
                "input-controls": request.get("input-controls", {}),
            },
            provider_cfg=provider_cfg,
        )
        output_text = str(provider_result.get("output") or "").strip()
        if not output_text:
            return None
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        findings = parsed.get("findings", [])
        recommendation = parsed.get("recommendation", "pass-with-notes")
        follow_up_actions = parsed.get("follow-up-actions", [])
        if isinstance(findings, list) and isinstance(follow_up_actions, list) and isinstance(recommendation, str):
            return build_review_report(
                review_id=review_id,
                subject=subject,
                reviewer=reviewer,
                criteria=criteria,
                findings=findings,
                recommendation=recommendation,
                follow_up_actions=follow_up_actions,
                created_at=(now_fn or now_iso_z)(),
            )
    except AudiaGenticError:
        return None
    return None


def _build_and_persist_review(
    project_root: Path,
    request: dict[str, Any],
    *,
    job_id: str,
    subject: dict[str, Any],
    review_id: str,
    reviewer: dict[str, Any],
    criteria: list[str],
    report_payload: dict[str, Any] | None,
    now_fn=None,
) -> dict[str, Any]:
    """Build the review report/bundle (with fallback) and persist them."""
    # Imported lazily to avoid a module import cycle with prompt_launch.
    from audiagentic.components.agent_jobs import jobs_store as store
    from audiagentic.components.agent_jobs.prompt_launch import prompt_launch_path

    report = report_payload or build_review_report(
        review_id=review_id,
        subject=subject,
        reviewer=reviewer,
        criteria=criteria,
        findings=[],
        recommendation="pass-with-notes",
        follow_up_actions=[],
        created_at=(now_fn or now_iso_z)(),
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
        updated_at=(now_fn or now_iso_z)(),
    )
    atomic_write_json(prompt_launch_path(project_root, job_id), request)
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


def launch_review_request(project_root: Path, request: dict[str, Any], *, now_fn=None) -> dict[str, Any]:
    """Run the review pipeline for a review-tagged prompt request."""
    # Imported lazily to avoid a module import cycle with prompt_launch.
    from audiagentic.components.agent_jobs.prompt_launch import _resolve_job_id

    job_id = _resolve_job_id(project_root, request, now_fn=now_fn)
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

    rendered_prompt = _render_review_prompt(
        project_root, request, provider_id=provider_id, subject=subject
    )
    prompt_for_criteria = request["prompt-body"].strip() or rendered_prompt.strip()
    criteria = [line.strip() for line in prompt_for_criteria.splitlines() if line.strip()]
    if not criteria:
        criteria = ["review the subject against the requested prompt"]

    report_payload = _execute_and_parse_review(
        project_root,
        request,
        provider_id=provider_id,
        provider_cfg=provider_cfg,
        job_id=job_id,
        subject=subject,
        review_id=review_id,
        reviewer=reviewer,
        criteria=criteria,
        rendered_prompt=rendered_prompt,
        now_fn=now_fn,
    )
    return _build_and_persist_review(
        project_root,
        request,
        job_id=job_id,
        subject=subject,
        review_id=review_id,
        reviewer=reviewer,
        criteria=criteria,
        report_payload=report_payload,
        now_fn=now_fn,
    )
