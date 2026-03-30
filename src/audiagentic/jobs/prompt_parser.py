"""Normalization for tagged interactive prompts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "prompt-launch-request.schema.json"

ALLOWED_TAGS = {"plan", "implement", "review", "audit", "check-in-prep"}
TAG_ALIASES = {
    "p": "plan",
    "i": "implement",
    "r": "review",
    "a": "audit",
    "c": "check-in-prep",
}
PROVIDER_ALIASES = {
    "local-openai": "local-openai",
    "lo": "local-openai",
    "codex": "codex",
    "cx": "codex",
    "claude": "claude",
    "cld": "claude",
    "gemini": "gemini",
    "gm": "gemini",
    "qwen": "qwen",
    "qw": "qwen",
    "copilot": "copilot",
    "cp": "copilot",
    "continue": "continue",
    "ctr": "continue",
    "cline": "cline",
    "cln": "cline",
}
DEFAULT_TARGET_KIND = "adhoc"
ALLOWED_DIRECTIVES = {
    "target",
    "job",
    "provider",
    "model",
    "model-alias",
    "profile",
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
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
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


def _default_adhoc_id(prompt_id: str) -> str:
    suffix = prompt_id.split("_", 1)[-1]
    return f"adh_{suffix}"


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
    tag_token = raw_tag[1:]
    provider_token = PROVIDER_ALIASES.get(tag_token)
    explicit_adhoc = False
    if tag_token == "adhoc":
        normalized_tag = "implement"
        explicit_adhoc = True
    elif tag_token in TAG_ALIASES:
        normalized_tag = TAG_ALIASES[tag_token]
    elif tag_token in ALLOWED_TAGS:
        normalized_tag = tag_token
    elif provider_token is not None:
        normalized_tag = "implement"
    else:
        raise AudiaGenticError(
            code="JOB-VALIDATION-028",
            kind="validation",
            message="unknown prompt tag",
            details={"tag": tag_token},
        )

    directives: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise AudiaGenticError(
                code="JOB-VALIDATION-029",
                kind="validation",
                message="prompt directive must use key=value",
                details={"token": token},
            )
        key, value = token.split("=", 1)
        if key not in ALLOWED_DIRECTIVES:
            raise AudiaGenticError(
                code="JOB-VALIDATION-030",
                kind="validation",
                message="unknown prompt directive",
                details={"directive": key},
            )
        if key in directives:
            raise AudiaGenticError(
                code="JOB-VALIDATION-031",
                kind="validation",
                message="duplicate prompt directive",
                details={"directive": key},
            )
        directives[key] = value

    resolved_provider = directives.get("provider") or provider_token or provider_id
    if provider_token is not None and directives.get("provider") is not None and directives["provider"] != provider_token:
        raise AudiaGenticError(
            code="JOB-VALIDATION-035",
            kind="validation",
            message="provider shorthand conflicts with provider directive",
            details={"provider-tag": provider_token, "provider": directives["provider"]},
        )
    if provider_id is not None and provider_token is not None and provider_id != provider_token:
        raise AudiaGenticError(
            code="JOB-VALIDATION-037",
            kind="validation",
            message="provider shorthand conflicts with provided provider-id",
            details={"provider-tag": provider_token, "provider-id": provider_id},
        )
    if provider_id is not None and directives.get("provider") is not None and provider_id != directives["provider"]:
        raise AudiaGenticError(
            code="JOB-VALIDATION-038",
            kind="validation",
            message="provider directive conflicts with provided provider-id",
            details={"provider-id": provider_id, "provider": directives["provider"]},
        )
    if resolved_provider is None:
        raise AudiaGenticError(
            code="JOB-VALIDATION-036",
            kind="validation",
            message="provider is required",
            details={},
        )

    target_value = directives.get("target")
    if target_value:
        target = _parse_target(target_value, adhoc_requested=tag_token == "adhoc")
        target_origin = "explicit"
    else:
        target = {"kind": DEFAULT_TARGET_KIND, "adhoc-id": _default_adhoc_id(prompt_id_value)}
        target_origin = "explicit" if explicit_adhoc else "default"
    if explicit_adhoc and allow_adhoc_target is False:
        # parser still accepts the request, but execution can stay gated.
        target["adhoc-id"] = target.get("adhoc-id") or "adhoc"

    if normalized_tag not in {"audit", "check-in-prep"} and not body.strip() and not explicit_adhoc:
        raise AudiaGenticError(
            code="JOB-VALIDATION-032",
            kind="validation",
            message="prompt body is required for this tag",
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
    if review_policy is not None:
        payload["review-policy"] = review_policy
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
