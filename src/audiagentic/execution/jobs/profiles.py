"""Workflow profile loader and validator."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError

BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "lite": {
        "profile-id": "lite",
        "stages": [
            {"id": "plan", "required": True},
            {"id": "implement", "required": True},
            {"id": "summary", "required": False},
        ],
    },
    "standard": {
        "profile-id": "standard",
        "stages": [
            {"id": "plan", "required": True},
            {"id": "implement", "required": True},
            {"id": "review", "required": True},
            {"id": "check-in-prep", "required": True},
        ],
    },
    "strict": {
        "profile-id": "strict",
        "stages": [
            {"id": "plan", "required": True},
            {"id": "approval", "required": True},
            {"id": "implement", "required": True},
            {"id": "review", "required": True},
            {"id": "audit", "required": True},
            {"id": "check-in-prep", "required": True},
            {"id": "approval", "required": True},
        ],
    },
}


def _ensure_profile_shape(profile: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if profile.get("profile-id") is None:
        issues.append("profile-id is required")
    stages = profile.get("stages")
    if not isinstance(stages, list) or not stages:
        issues.append("stages must be a non-empty list")
        return issues
    for idx, stage in enumerate(stages):
        if not isinstance(stage, dict):
            issues.append(f"stage {idx} must be an object")
            continue
        if "id" not in stage:
            issues.append(f"stage {idx} missing id")
        if "required" not in stage:
            issues.append(f"stage {idx} missing required")
        if "required" in stage and not isinstance(stage["required"], bool):
            issues.append(f"stage {idx} required must be boolean")
    return issues


def validate_profile(profile: dict[str, Any]) -> list[str]:
    issues = _ensure_profile_shape(profile)
    return issues


def load_builtin_profiles() -> dict[str, dict[str, Any]]:
    return deepcopy(BUILTIN_PROFILES)


def _stage_index(stages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        index.setdefault(stage["id"], []).append(stage)
    return index


def apply_overrides(profile: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    issues = validate_profile(profile)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-007",
            kind="validation",
            message="profile failed validation",
            details={"issues": issues},
        )
    if not overrides:
        return deepcopy(profile)

    merged = deepcopy(profile)
    stage_map = _stage_index(merged["stages"])
    for stage_id, override in overrides.items():
        if stage_id not in stage_map:
            raise AudiaGenticError(
                code="JOB-VALIDATION-008",
                kind="validation",
                message="override references unknown stage id",
                details={"stage-id": stage_id},
            )
        if not isinstance(override, dict):
            raise AudiaGenticError(
                code="JOB-VALIDATION-009",
                kind="validation",
                message="override entry must be an object",
                details={"stage-id": stage_id},
            )
        if "enabled" not in override or not isinstance(override["enabled"], bool):
            raise AudiaGenticError(
                code="JOB-VALIDATION-010",
                kind="validation",
                message="override must include boolean enabled",
                details={"stage-id": stage_id},
            )
        if any(stage["required"] for stage in stage_map[stage_id]) and not override["enabled"]:
            raise AudiaGenticError(
                code="JOB-BUSINESS-002",
                kind="business-rule",
                message="required stages may not be disabled",
                details={"stage-id": stage_id},
            )
        for stage in stage_map[stage_id]:
            stage["enabled"] = override["enabled"]
    for stage in merged["stages"]:
        stage.setdefault("enabled", True)
    return merged


def _parse_overrides_yaml(text: str) -> dict[str, dict[str, bool]]:
    overrides: dict[str, dict[str, bool]] = {}
    current_section: str | None = None
    current_stage: str | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, _, value = raw.strip().partition(":")
        if indent == 0:
            if key != "workflow-overrides":
                raise AudiaGenticError(
                    code="JOB-VALIDATION-011",
                    kind="validation",
                    message="unexpected root key in workflow overrides",
                    details={"key": key},
                )
            current_section = "workflow-overrides"
            current_stage = None
            continue
        if current_section != "workflow-overrides":
            continue
        if indent == 2:
            current_stage = key
            overrides[current_stage] = {}
            continue
        if indent == 4 and current_stage:
            if key != "enabled":
                raise AudiaGenticError(
                    code="JOB-VALIDATION-012",
                    kind="validation",
                    message="unexpected override field",
                    details={"stage-id": current_stage, "field": key},
                )
            value_norm = value.strip().lower()
            if value_norm not in {"true", "false"}:
                raise AudiaGenticError(
                    code="JOB-VALIDATION-013",
                    kind="validation",
                    message="override enabled must be true or false",
                    details={"stage-id": current_stage},
                )
            overrides[current_stage]["enabled"] = value_norm == "true"
    return overrides


def load_workflow_overrides(path: Path) -> dict[str, dict[str, bool]]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    if text.lstrip().startswith("{"):
        payload = json.loads(text)
        return payload.get("workflow-overrides", {})
    return _parse_overrides_yaml(text)


def load_profile(
    profile_id: str,
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    builtins = load_builtin_profiles()
    if profile_id not in builtins:
        raise AudiaGenticError(
            code="JOB-VALIDATION-014",
            kind="validation",
            message="unknown workflow profile",
            details={"profile-id": profile_id},
        )
    profile = builtins[profile_id]
    return apply_overrides(profile, overrides or {})
