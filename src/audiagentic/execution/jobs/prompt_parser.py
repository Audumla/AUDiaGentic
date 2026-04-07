"""Normalization for tagged interactive prompts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.contracts.schema_registry import read_schema
from audiagentic.execution.jobs.prompt_syntax import load_canonical_tags, load_no_body_required_tags, load_review_tag, load_prompt_syntax
from audiagentic.execution.jobs.prompt_templates import load_prompt_template
from audiagentic.config.provider_config import load_provider_config

REPO_ROOT = Path(__file__).resolve().parents[4]

SHORT_TAG_PROVIDER_SEPARATOR = "-"
DEFAULT_TARGET_KIND = "adhoc"
# Fallback used before a project root is available; overridden per-call from config.
ALLOWED_TAGS = load_canonical_tags({})
ALLOWED_DIRECTIVES = {
    "target",
    "job",
    "provider",
    "model",
    "model-alias",
    "profile",
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
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_prompt_id(*, now_fn=None) -> str:
    timestamp = (now_fn or _now_timestamp)()
    compact = timestamp.replace("-", "").replace(":", "").replace("Z", "").replace("T", "_")
    return f"prm_{compact[:15]}"


def validate_prompt_launch_request(payload: dict[str, Any]) -> list[str]:
    schema = read_schema("prompt-launch-request")
    validator = Draft202012Validator(schema)
    return sorted(error.message for error in validator.iter_errors(payload))


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise AudiaGenticError(
        code="JOB-VALIDATION-023",
        kind="validation",
        message="boolean directive must be true or false",
        details={"value": value},
    )


def _parse_target(value: str, *, adhoc_requested: bool) -> dict[str, Any]:
    if adhoc_requested:
        payload: dict[str, Any] = {"kind": "adhoc"}
        if value:
            payload["adhoc-id"] = value
        return payload
    if ":" not in value:
        raise AudiaGenticError(
            code="JOB-VALIDATION-024",
            kind="validation",
            message="target directive must use kind:value",
            details={"value": value},
        )
    kind, ref = value.split(":", 1)
    if kind == "packet":
        return {"kind": "packet", "packet-id": ref}
    if kind == "job":
        return {"kind": "job", "job-id": ref}
    if kind == "artifact":
        if "/" in ref or ref.startswith("."):
            return {"kind": "artifact", "artifact-path": ref}
        return {"kind": "artifact", "artifact-id": ref}
    if kind == "adhoc":
        return {"kind": "adhoc", "adhoc-id": ref or None}
    raise AudiaGenticError(
        code="JOB-VALIDATION-025",
        kind="validation",
        message="unknown target kind",
        details={"kind": kind},
    )


def _infer_target_from_id(value: str, *, tag: str, review_tag: str) -> dict[str, Any]:
    normalized = value.strip()
    if not normalized:
        return {"kind": DEFAULT_TARGET_KIND, "adhoc-id": normalized}
    if ":" in normalized:
        return _parse_target(normalized, adhoc_requested=False)
    if normalized.startswith("PKT-"):
        return {"kind": "packet", "packet-id": normalized}
    if normalized.startswith("job_") or normalized.startswith("job-") or normalized.startswith("job"):
        return {"kind": "job", "job-id": normalized}
    if "/" in normalized or "\\" in normalized or normalized.endswith(".md") or normalized.endswith(".json"):
        return {"kind": "artifact", "artifact-path": normalized}
    if tag == review_tag:
        return {"kind": "job", "job-id": normalized}
    return {"kind": DEFAULT_TARGET_KIND, "adhoc-id": normalized}


def _split_prompt_text(prompt_text: str) -> tuple[str, str]:
    lines = prompt_text.splitlines()
    first_index = None
    for index, line in enumerate(lines):
        if line.strip():
            first_index = index
            break
    if first_index is None:
        raise AudiaGenticError(
            code="JOB-VALIDATION-026",
            kind="validation",
            message="prompt body is empty",
            details={},
        )
    header = lines[first_index].strip()
    body = "\n".join(lines[first_index + 1 :]).lstrip("\n")
    return header, body


def _split_tag_and_provider(raw_tag: str, *, tag_aliases: dict[str, str], generic_tag: str, allowed_tags: set[str]) -> tuple[str, str | None]:
    tag_token = raw_tag[1:]
    if SHORT_TAG_PROVIDER_SEPARATOR not in tag_token:
        return tag_token, None
    tag_part, provider_part = tag_token.split(SHORT_TAG_PROVIDER_SEPARATOR, 1)
    if tag_part in tag_aliases or tag_part in allowed_tags or tag_part == generic_tag:
        return tag_part, provider_part or None
    return tag_token, None


def _normalize_alias_map(alias_map: dict[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(alias_map, dict):
        return normalized
    for raw_key, raw_value in alias_map.items():
        if isinstance(raw_key, str) and isinstance(raw_value, str) and raw_key:
            normalized[raw_key] = raw_value
    return normalized


def _normalize_directives(raw_directives: dict[str, str], alias_map: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, value in raw_directives.items():
        key = alias_map.get(raw_key, raw_key)
        if key in normalized:
            raise AudiaGenticError(
                code="JOB-VALIDATION-031",
                kind="validation",
                message="duplicate prompt directive",
                details={"directive": key},
            )
        normalized[key] = value
    return normalized


def _normalize_provider(value: str | None, alias_map: dict[str, str]) -> str | None:
    if value is None:
        return None
    return alias_map.get(value, value)


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
            code="JOB-VALIDATION-027",
            kind="validation",
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
            code="JOB-VALIDATION-028",
            kind="validation",
            message="unknown prompt tag",
            details={"tag": tag_token},
        )

    raw_directives: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise AudiaGenticError(
                code="JOB-VALIDATION-029",
                kind="validation",
                message="prompt directive must use key=value",
                details={"token": token},
            )
        key, value = token.split("=", 1)
        if key in raw_directives:
            raise AudiaGenticError(
                code="JOB-VALIDATION-031",
                kind="validation",
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
            code="JOB-VALIDATION-035",
            kind="validation",
            message="provider shorthand conflicts with provider directive",
            details={"provider-tag": provider_token, "provider": raw_directives.get("provider")},
        )
    if provider_suffix_value is not None and directive_provider is not None and provider_suffix_value != directive_provider:
        raise AudiaGenticError(
            code="JOB-VALIDATION-039",
            kind="validation",
            message="provider shorthand conflicts with provider directive",
            details={"provider-tag": provider_suffix, "provider": raw_directives.get("provider")},
        )
    if resolved_provider is None:
        raise AudiaGenticError(
            code="JOB-VALIDATION-036",
            kind="validation",
            message="provider is required",
            details={},
        )

    syntax_profile_name = None
    if project_root is not None:
        try:
            provider_config = load_provider_config(project_root).get("providers", {})
            provider_cfg = provider_config.get(resolved_provider, {})
            prompt_surface = provider_cfg.get("prompt-surface")
            if isinstance(prompt_surface, dict):
                selected_profile = prompt_surface.get("settings-profile")
                if isinstance(selected_profile, str) and selected_profile.strip():
                    syntax_profile_name = selected_profile.strip()
        except AudiaGenticError:
            syntax_profile_name = None

    if syntax_profile_name:
        prompt_syntax = load_prompt_syntax(project_root, profile_name=syntax_profile_name)
    directive_aliases = _normalize_alias_map(prompt_syntax.get("directive-aliases"))
    directives = _normalize_directives(raw_directives, directive_aliases)
    for key in directives:
        if key not in ALLOWED_DIRECTIVES:
            raise AudiaGenticError(
                code="JOB-VALIDATION-030",
                kind="validation",
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
            code="JOB-VALIDATION-032",
            kind="validation",
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
            code="JOB-VALIDATION-033",
            kind="validation",
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
            code="JOB-VALIDATION-034",
            kind="validation",
            message="prompt launch request failed validation",
            details={"issues": issues},
        )
    return payload
