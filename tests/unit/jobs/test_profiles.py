from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.jobs.profiles import (
    BUILTIN_PROFILES,
    apply_overrides,
    load_profile,
    load_workflow_overrides,
    validate_profile,
)


def test_builtin_profiles_validate() -> None:
    for profile in BUILTIN_PROFILES.values():
        assert not validate_profile(profile)


def test_profile_override_disables_optional_stage() -> None:
    overrides = {"summary": {"enabled": False}}
    profile = load_profile("lite", overrides=overrides)
    summary = [stage for stage in profile["stages"] if stage["id"] == "summary"][0]
    assert summary["enabled"] is False
    required = [stage for stage in profile["stages"] if stage["id"] in {"plan", "implement"}]
    assert all(stage["enabled"] is True for stage in required)


def test_profile_override_rejects_disabling_required_stage() -> None:
    try:
        load_profile("lite", overrides={"plan": {"enabled": False}})
    except AudiaGenticError as exc:
        assert exc.kind == "business-rule"
    else:
        raise AssertionError("expected required stage disable error")


def test_profile_override_rejects_unknown_stage() -> None:
    try:
        load_profile("lite", overrides={"unknown": {"enabled": False}})
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected unknown stage override error")


def test_profile_override_idempotent() -> None:
    base = BUILTIN_PROFILES["lite"]
    overrides = {"summary": {"enabled": False}}
    once = apply_overrides(base, overrides)
    twice = apply_overrides(once, overrides)
    assert once == twice


def test_load_workflow_overrides_yaml() -> None:
    overrides = load_workflow_overrides(
        ROOT / "docs" / "examples" / "fixtures" / "workflow-overrides.valid.yaml"
    )
    assert overrides["summary"]["enabled"] is False


def test_load_workflow_overrides_invalid_yaml() -> None:
    try:
        load_workflow_overrides(
            ROOT / "docs" / "examples" / "fixtures" / "workflow-overrides.invalid.yaml"
        )
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected invalid override error")
