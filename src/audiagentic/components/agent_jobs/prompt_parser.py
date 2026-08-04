"""Normalization for tagged interactive prompts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs.prompt_aliases import (
    _normalize_alias_map,
    _normalize_directives,
    _normalize_provider,
    _split_tag_and_provider,
)
from audiagentic.components.agent_jobs.prompt_syntax import (
    load_canonical_tags,
    load_no_body_required_tags,
    load_prompt_syntax,
    load_review_tag,
)
from audiagentic.components.agent_jobs.prompt_targets import (
    DEFAULT_TARGET_KIND,
    _infer_target_from_id,
    _parse_target,
)
from audiagentic.components.agent_jobs.prompt_templates import load_prompt_template
from audiagentic.components.providers.providers_api import get_provider_prompt_settings_profile
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.time import now_iso_z

# Fallback used before a project root is available; overridden per-call from config.
ALLOWED_TAGS = load_canonical_tags({})
ALLOWED_DIRECTIVES = {
    "target",
    "job",
    "provider",
    "model",
    "model-alias",
    "profile",
    "execution-profile-id",
    "id",
    "subject",
    "context",
    "ctx",
    "output",
    "out",
    "template",
    "t",
    "review-count",
    "aggregation",
    "distinct-reviewers",
    "require-distinct-reviewers",
    "commit-scope",
}


def _now_timestamp() -> str:
    return now_iso_z()


def generate_prompt_id(*, now_fn=None) -> str:
    timestamp = (now_fn or _now_timestamp)()
    compact = timestamp.replace("-", "").replace(":", "").replace("Z", "").replace("T", "_")
    return f"prm_{compact[:15]}"


def validate_prompt_launch_request(payload: dict[str, Any]) -> list[str]:
    return validate_with_schema("prompt-launch-request", payload)


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise AudiaGenticError(
        code="VAL-PPARSE-001",
        kind="agent-jobs",
        message="boolean directive must be true or false",
        details={"value": value},
    )


def _split_prompt_text(prompt_text: str) -> tuple[str, str]:
    lines = prompt_text.splitlines()
    first_index = None
    for index, line in enumerate(lines):
        if line.strip():
            first_index = index
            break
    if first_index is None:
        raise AudiaGenticError(
            code="VAL-PPARSE-004",
            kind="agent-jobs",
            message="prompt body is empty",
            details={},
        )
    header = lines[first_index].strip()
    body = "\n".join(lines[first_index + 1 :]).lstrip("\n")
    return header, body


def _default_adhoc_id(prompt_id: str) -> str:
    suffix = prompt_id.split("_", 1)[-1]
    return f"adh_{suffix}"


def _has_default_prompt_template(project_root: Path | None, *, tag: str, provider_id: str | None) -> bool:
    if project_root is None or provider_id is None:
        return False
    template_text, _ = load_prompt_template(project_root, tag=tag, provider_id=provider_id, template_name=None)
    return bool(template_text)


def parse_prompt_launch_request(
    prompt_text: str,
    *,
    surface: str,
    provider_id: str | None = None,
    session_id: str | None = None,
    model_id: str | None = None,
    model_alias: str | None = None,
    workflow_profile: str = "standard",
    prompt_id: str | None = None,
    allow_adhoc_target: bool | None = None,
    default_review_policy: dict[str, Any] | None = None,
    stream_controls: dict[str, Any] | None = None,
    input_controls: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    header, body = _split_prompt_text(prompt_text)
    tokens = header.split()
    raw_tag = tokens[0]
    if not raw_tag.startswith("@"):
        raise AudiaGenticError(
            code="VAL-PPARSE-006",
            kind="agent-jobs",
            message="prompt must begin with a tag token",
            details={"header": header},
        )
    prompt_id_value = prompt_id or generate_prompt_id()
    prompt_syntax = load_prompt_syntax(project_root)
    tag_aliases = _normalize_alias_map(prompt_syntax.get("tag-aliases"))
    provider_aliases = _normalize_alias_map(prompt_syntax.get("provider-aliases"))
    generic_tag = str(prompt_syntax.get("generic-tag") or "adhoc")
    allowed_tags = load_canonical_tags(prompt_syntax)
    no_body_required_tags = load_no_body_required_tags(prompt_syntax)
    review_tag = load_review_tag(prompt_syntax)
    implement_tag = str(prompt_syntax.get("implement-tag") or "ag-implement")

    tag_token, provider_suffix = _split_tag_and_provider(raw_tag, tag_aliases=tag_aliases, generic_tag=generic_tag, allowed_tags=allowed_tags)
    provider_token = provider_aliases.get(tag_token)
    explicit_adhoc = False
    if tag_token == generic_tag:
        normalized_tag = implement_tag
        explicit_adhoc = True
    elif tag_token in tag_aliases:
        alias_value = tag_aliases[tag_token]
        if alias_value == generic_tag:
            normalized_tag = implement_tag
            explicit_adhoc = True
        else:
            normalized_tag = alias_value
    elif tag_token in allowed_tags:
        normalized_tag = tag_token
    elif provider_token is not None:
        normalized_tag = implement_tag
    else:
        raise AudiaGenticError(
            code="VAL-PPARSE-007",
            kind="agent-jobs",
            message="unknown prompt tag",
            details={"tag": tag_token},
        )

    raw_directives: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise AudiaGenticError(
                code="VAL-PPARSE-008",
                kind="agent-jobs",
                message="prompt directive must use key=value",
                details={"token": token},
            )
        key, value = token.split("=", 1)
        if key in raw_directives:
            raise AudiaGenticError(
                code="VAL-PPARSE-009",
                kind="agent-jobs",
                message="duplicate prompt directive",
                details={"directive": key},
            )
        raw_directives[key] = value

    directive_provider = _normalize_provider(raw_directives.get("provider"), provider_aliases)
    provider_suffix_value = _normalize_provider(provider_suffix, provider_aliases)
    provider_id_value = _normalize_provider(provider_id, provider_aliases)
    resolved_provider = directive_provider or provider_token or provider_suffix_value or provider_id_value
    if provider_token is not None and directive_provider is not None and directive_provider != provider_token:
        raise AudiaGenticError(
            code="VAL-PPARSE-010",
            kind="agent-jobs",
            message="provider shorthand conflicts with provider directive",
            details={"provider-tag": provider_token, "provider": raw_directives.get("provider")},
        )
    if provider_suffix_value is not None and directive_provider is not None and provider_suffix_value != directive_provider:
        raise AudiaGenticError(
            code="VAL-PPARSE-011",
            kind="agent-jobs",
            message="provider shorthand conflicts with provider directive",
            details={"provider-tag": provider_suffix, "provider": raw_directives.get("provider")},
        )
    if resolved_provider is None:
        raise AudiaGenticError(
            code="VAL-PPARSE-012",
            kind="agent-jobs",
            message="provider is required",
            details={},
        )

    syntax_profile_name = None
    if project_root is not None:
        try:
            syntax_profile_name = get_provider_prompt_settings_profile(
                project_root,
                resolved_provider,
            )
        except AudiaGenticError:
            syntax_profile_name = None

    if syntax_profile_name:
        prompt_syntax = load_prompt_syntax(project_root, profile_name=syntax_profile_name)
    directive_aliases = _normalize_alias_map(prompt_syntax.get("directive-aliases"))
    directives = _normalize_directives(raw_directives, directive_aliases)
    for key in directives:
        if key not in ALLOWED_DIRECTIVES:
            raise AudiaGenticError(
                code="VAL-PPARSE-013",
                kind="agent-jobs",
                message="unknown prompt directive",
                details={"directive": key},
            )

    prompt_controls: dict[str, Any] = {}
    if "id" in directives:
        prompt_controls["id"] = directives["id"]
    if "context" in directives:
        prompt_controls["context"] = directives["context"]
    if "output" in directives:
        prompt_controls["output"] = directives["output"]
    if "template" in directives:
        prompt_controls["template"] = directives["template"]

    target_value = directives.get("target")
    id_value = directives.get("id")
    if target_value:
        target = _parse_target(target_value, adhoc_requested=tag_token == generic_tag)
        target_origin = "explicit"
    elif id_value:
        target = _infer_target_from_id(id_value, tag=normalized_tag, review_tag=review_tag)
        target_origin = "explicit"
    else:
        target = {"kind": DEFAULT_TARGET_KIND, "adhoc-id": _default_adhoc_id(prompt_id_value)}
        target_origin = "explicit" if explicit_adhoc else "default"
    if explicit_adhoc and allow_adhoc_target is False:
        # parser still accepts the request, but execution can stay gated.
        target["adhoc-id"] = target.get("adhoc-id") or "adhoc"

    has_template_fallback = prompt_controls.get("template") or _has_default_prompt_template(
        project_root,
        tag=normalized_tag,
        provider_id=resolved_provider,
    )
    if normalized_tag not in no_body_required_tags and not body.strip() and not (explicit_adhoc or has_template_fallback):
        raise AudiaGenticError(
            code="VAL-PPARSE-014",
            kind="agent-jobs",
            message="prompt body is required for this tag unless a template is selected",
            details={"tag": normalized_tag},
        )

    review_policy = default_review_policy
    if "review-count" in directives or "aggregation" in directives or "distinct-reviewers" in directives:
        review_policy = {
            "required-reviews": int(directives.get("review-count", "1")),
            "aggregation-rule": directives.get("aggregation", "all-pass"),
            "require-distinct-reviewers": _parse_bool(
                directives.get("require-distinct-reviewers", directives.get("distinct-reviewers", "true"))
            ),
        }
    if review_policy is not None and review_policy.get("aggregation-rule") == "majority-pass":
        raise AudiaGenticError(
            code="CON-PPARSE-001",
            kind="agent-jobs",
            message="majority-pass is not enabled in the first executable pass",
            details={},
        )

    payload: dict[str, Any] = {
        "contract-version": "v1",
        "prompt-id": prompt_id_value,
        "source": {
            "kind": "interactive-prompt",
            "surface": surface,
            "provider-id": resolved_provider,
            "session-id": session_id,
            "model-id": directives.get("model", model_id),
            "model-alias": directives.get("model-alias", model_alias),
        },
        "tag": normalized_tag,
        "target": target,
        "target-origin": target_origin,
        "workflow-profile": directives.get("profile", workflow_profile),
        "existing-job-id": directives.get("job"),
        "prompt-body": body,
    }
    if "execution-profile-id" in directives:
        payload["execution-profile-id"] = directives["execution-profile-id"]
    if prompt_controls:
        payload["prompt-controls"] = prompt_controls
    if review_policy is not None:
        payload["review-policy"] = review_policy
    if stream_controls is not None:
        payload["stream-controls"] = stream_controls
    if input_controls is not None:
        payload["input-controls"] = input_controls
    if "commit-scope" in directives:
        payload["commit-scope"] = directives["commit-scope"]
    issues = validate_prompt_launch_request(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PPARSE-015",
            kind="agent-jobs",
            message="prompt launch request failed validation",
            details={"issues": issues},
        )
    return payload
