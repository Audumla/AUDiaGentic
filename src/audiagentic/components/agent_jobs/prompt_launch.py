"""Prompt-to-job launch helpers."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs.prompt_context import (
    build_prompt_context_from_request,
    load_session_data,
    to_template_dict,
)
from audiagentic.components.agent_jobs.prompt_syntax import (
    load_prompt_syntax,
    load_review_tag,
)
from audiagentic.components.agent_jobs.prompt_templates import (
    load_prompt_from_file,
    render_prompt_template,
)
from audiagentic.components.providers.providers_api import (
    is_provider_enabled_for_launch as is_provider_enabled,
)
from audiagentic.components.providers.providers_api import (
    resolve_launch_model,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.templates import has_placeholders
from audiagentic.foundation.time import now_iso_z


def _canonical_work_context_id(request: dict[str, Any]) -> str | None:
    """Return the caller-owned Context for a migrated prompt launch.

    A Context is deliberately required here.  Creating one implicitly from a
    legacy prompt request would give replay a new Context and would violate
    the canonical Context/Work identity contract.
    """
    value = request.get("context-id") or request.get("context_id")
    return value if isinstance(value, str) and value else None


def _submit_canonical_work(
    project_root: Path,
    request: dict[str, Any],
    *,
    now_fn=None,
) -> dict[str, Any] | None:
    """Submit a Context-backed prompt through Agents Work/Gateway."""
    context_id = _canonical_work_context_id(request)
    if context_id is None:
        raise AudiaGenticError(
            code="VAL-AGW-001",
            kind="agents",
            message="prompt launches require a context-id",
            details={"prompt-id": request.get("prompt-id")},
        )

    from audiagentic.components.agents.gateway.client import get_gateway_client
    from audiagentic.components.agents.work.ingress import deterministic_work_id

    provider_id, resolved_model, resolved_alias = _resolve_agent_provider_model(
        project_root, request
    )
    selection = resolve_launch_model(
        project_root,
        provider_id=provider_id,
        model_id=resolved_model or request["source"].get("model-id"),
        model_alias=resolved_alias or request["source"].get("model-alias"),
    )
    work_id = deterministic_work_id(
        source="prompt-launch",
        delivery_id=f"{context_id}:{request['prompt-id']}",
    )
    prepared = _render_launch_prompt(
        project_root,
        request,
        job_id=work_id,
        provider_id=provider_id,
        model_id=selection.get("model-id"),
    )
    source = prepared.get("source") if isinstance(prepared.get("source"), dict) else {}
    provenance = {
        "prompt-id": prepared["prompt-id"],
        "surface": source.get("surface"),
        "session-id": source.get("session-id"),
        "provider-id": provider_id,
        "model-id": selection.get("model-id"),
        "model-alias": selection.get("model-alias"),
        "tag": prepared["tag"],
        "target": prepared["target"],
        "workflow-profile": prepared["workflow-profile"],
    }
    record = get_gateway_client(project_root).submit_agent_work(
        project_root,
        context_id,
        {
            "message_id": f"prompt:{prepared['prompt-id']}",
            "text": prepared.get("prompt-body", ""),
            "inputs": {"prompt-provenance": provenance},
            "created_at": (now_fn or now_iso_z)(),
        },
        work_id=work_id,
    )
    return {
        "status": "submitted",
        "work-id": record["work_id"],
        "context-id": record["context_id"],
        "work": record,
    }


def load_project_config(project_root: Path) -> dict[str, Any]:
    path = project_root / ".audiagentic" / "config" / "project.yaml"
    return load_yaml_file(path)


def _first_instance_model_id(project_root: Path, resolved: dict[str, Any]) -> str | None:
    """AS105/AS101: resolve a profile's first instance to a concrete model-id.

    This function's contract returns a single model_id; a genuinely
    multi-instance profile only has its first instance represented here.
    Acceptable for this legacy launch path, pending its rework (superseded
    by the harness-native Skill launch path).
    """
    instances = resolved.get("instances") or []
    if not instances:
        return None
    from audiagentic.components.agents.gateway.instances import resolve_instance_facts

    facts = resolve_instance_facts(project_root, (instances[0],))
    return facts[0].model_id


def _resolve_agent_provider_model(
    project_root: Path,
    request: dict[str, Any],
) -> tuple[str, str | None, str | None]:
    """Resolve provider_id, model_id, model_alias from execution profile or request.

    Precedence:
      1. execution-profile-id in request -> resolve profile -> override provider/model
      2. Explicit provider-id / model-id in request source
      3. Default execution profile
      4. Fallback to local-openai (backward compat)

    Returns (provider_id, model_id, model_alias).
    """
    source = request.get("source", {})
    explicit_provider = source.get("provider-id")
    explicit_model = source.get("model-id")
    explicit_alias = source.get("model-alias")

    execution_profile_id = request.get("execution-profile-id")
    if execution_profile_id:
        from audiagentic.components.agents.configuration.global_catalog import (
            resolve_global_execution_profile as resolve_execution_profile,
        )
        resolved = resolve_execution_profile(project_root, execution_profile_id)
        provider_id = resolved["provider_id"]
        if not is_provider_enabled(project_root, provider_id):
            raise AudiaGenticError(
                code="CON-AGJ-002",
                kind="agent-jobs",
                message="execution profile references a disabled provider",
                details={
                    "profile_id": execution_profile_id,
                    "provider_id": provider_id,
                },
            )
        return provider_id, _first_instance_model_id(project_root, resolved), resolved.get("model_alias")

    if explicit_provider or explicit_model:
        return explicit_provider or "local-openai", explicit_model, explicit_alias

    try:
        from audiagentic.components.agents.configuration.global_catalog import (
            resolve_global_default_execution_profile as resolve_default_execution_profile,
        )
        resolved = resolve_default_execution_profile(project_root)
        provider_id = resolved["provider_id"]
        if not is_provider_enabled(project_root, provider_id):
            raise AudiaGenticError(
                code="CON-AGJ-002",
                kind="agent-jobs",
                message="default execution profile references a disabled provider",
                details={
                    "profile_id": resolved["profile_id"],
                    "provider_id": provider_id,
                },
            )
        return provider_id, _first_instance_model_id(project_root, resolved), resolved.get("model_alias")
    except AudiaGenticError as exc:
        if exc.code == "RES-EXP-003":
            raise AudiaGenticError(
                code="CON-AGJ-001",
                kind="agent-jobs",
                message="no default execution profile and no explicit provider/model in request",
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


def _render_launch_prompt(
    project_root: Path,
    request: dict[str, Any],
    *,
    job_id: str,
    provider_id: str,
    model_id: str | None,
) -> dict[str, Any]:
    """Render the launch prompt through the shared context pipeline (EDJ25).

    Returns a copy of *request* whose ``prompt-body`` carries the rendered
    text and whose caller ``context`` is dropped (never persisted).  A
    template-free inline body (no placeholders, no template file) passes
    through byte-identical — the compatibility keystone for existing direct
    launches.
    """
    template_file = request.get("prompt-template-file")
    if template_file:
        source_text, _ = load_prompt_from_file(
            project_root, template_file, source_label=f"Prompt {request.get('prompt-id', '')!r}"
        )
    else:
        source_text = request.get("prompt-body", "")

    prepared = dict(request)
    explicit_context = prepared.pop("context", None)

    if not template_file and not has_placeholders(source_text):
        prepared["prompt-body"] = source_text
        return prepared

    session_id = request.get("source", {}).get("session-id") or ""
    session_data = load_session_data(project_root, session_id) if session_id else None

    context = build_prompt_context_from_request(
        request=request,
        project_root=str(project_root),
        project_id=load_project_config(project_root).get("project-id", ""),
        job_id=job_id,
        execution_profile_id=request.get("execution-profile-id") or "",
        provider_id=provider_id,
        model_id=model_id or "",
        explicit_context=explicit_context if isinstance(explicit_context, dict) else None,
        session_data=session_data,
    )
    prepared["prompt-body"] = render_prompt_template(source_text, to_template_dict(context))
    return prepared


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
    # ``adhoc`` is the generic fallback when no review action is registered;
    # it must never accidentally enter the review pipeline.
    if review_tag != "adhoc" and request["tag"] == review_tag:
        parent_work_id = request.get("parent-work-id") or request.get("work-id")
        if not isinstance(parent_work_id, str) or not parent_work_id:
            raise AudiaGenticError(
                code="VAL-AGW-REVIEW-001",
                kind="agents",
                message="review prompts must be submitted as child Work with a parent work-id",
            )
        from audiagentic.components.agents.work.work_api import submit_review

        source = request.get("source") if isinstance(request.get("source"), dict) else {}
        reviewer_key = ":".join(
            str(source.get(key) or "") for key in ("provider-id", "surface", "session-id")
        ).strip(":")
        child = submit_review(
            project_root,
            parent_work_id,
            review_key=f"{request['prompt-id']}:{reviewer_key or 'default'}",
            prompt=str(request.get("prompt-body") or "Review the parent Work."),
        )
        return {"status": "submitted", "work-id": child["work_id"], "parent-work-id": parent_work_id}
    return _submit_canonical_work(project_root, request, now_fn=now_fn)
