"""Schema-validation tests for the Hindsight RecipeSpec assembler (SL15 gate 4).

validate_recipe_spec is wired into assemble_hindsight_recipe, so a malformed
spec fails loudly with a canonical AudiaGenticError rather than producing a
broken recipe. These cases pin each reachable VAL-RSPEC failure and the two
happy-path assemblies.
"""
from __future__ import annotations

import pytest

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.recipe_spec import (
    ParamBinding,
    RecipeSpec,
    StatusOverride,
    assemble_hindsight_recipe,
    validate_recipe_spec,
)
from audiagentic.components.providers.services.recipes import ProviderRecipeKind
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _row(**kw) -> HindsightRecipeRow:
    base = dict(
        provider_id="spec-test",
        display_name="Spec Test",
        integration_type="test",
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        source_url="https://src.example/doc",
        source_date="2026-01-01",
        audia_action="manage_config_writes",
    )
    base.update(kw)
    return HindsightRecipeRow(**base)


def _backend() -> HindsightBackendConfig:
    return HindsightBackendConfig(base_url="https://hs.example.com", server_name="hs")


# --- validate_recipe_spec: each reachable failure --------------------------

def test_unknown_pattern_flagged():
    errors = validate_recipe_spec(RecipeSpec(pattern="nope"))  # type: ignore[arg-type]
    assert any("VAL-RSPEC-001" in e for e in errors)


def test_binding_with_both_row_field_and_literal_flagged():
    spec = RecipeSpec(
        pattern="no_automation",
        params=[ParamBinding(param_name="action_needed", row_field="notes", literal="x")],
    )
    assert any("VAL-RSPEC-002" in e for e in validate_recipe_spec(spec))


def test_unknown_row_field_flagged():
    spec = RecipeSpec(
        pattern="no_automation",
        params=[ParamBinding(param_name="action_needed", row_field="does_not_exist")],
    )
    assert any("VAL-RSPEC-003" in e for e in validate_recipe_spec(spec))


def test_declared_step_missing_required_binding_flagged():
    # declared_step requires install_steps + uninstall_steps row bindings
    spec = RecipeSpec(
        pattern="declared_step",
        params=[ParamBinding(param_name="install_steps", row_field="install_steps")],
    )
    errors = validate_recipe_spec(spec)
    assert any("VAL-RSPEC-004" in e and "uninstall_steps" in e for e in errors)


def test_duplicate_status_override_methods_flagged():
    spec = RecipeSpec(
        pattern="no_automation",
        status_overrides=[
            StatusOverride(method="probe", state="absent", status_text="a"),
            StatusOverride(method="probe", state="absent", status_text="b"),
        ],
    )
    assert any("VAL-RSPEC-005" in e for e in validate_recipe_spec(spec))


def test_valid_spec_has_no_errors():
    spec = RecipeSpec(
        pattern="no_automation",
        params=[ParamBinding(param_name="action_needed", row_field="notes")],
    )
    assert validate_recipe_spec(spec) == []


# --- assemble_hindsight_recipe: raises on invalid, builds on valid ---------

def test_assemble_raises_canonical_error_on_invalid_spec():
    spec = RecipeSpec(pattern="bogus")  # type: ignore[arg-type]
    with pytest.raises(AudiaGenticError) as exc:
        assemble_hindsight_recipe(_row(), _backend(), spec)
    assert exc.value.code == "VAL-RSPEC-009"
    assert "VAL-RSPEC-001" in exc.value.message


def test_declared_step_without_backend_raises():
    spec = RecipeSpec(
        pattern="declared_step",
        params=[
            ParamBinding(param_name="install_steps", row_field="install_steps"),
            ParamBinding(param_name="uninstall_steps", row_field="uninstall_steps"),
        ],
    )
    with pytest.raises(AudiaGenticError) as exc:
        assemble_hindsight_recipe(_row(), None, spec)
    assert exc.value.code == "VAL-RSPEC-011"


def test_no_automation_assembles_and_provisions():
    spec = RecipeSpec(
        pattern="no_automation",
        params=[ParamBinding(param_name="action_needed", row_field="notes")],
    )
    recipe = assemble_hindsight_recipe(_row(notes="do the thing"), None, spec)
    result = recipe.provision({})
    assert result.success
    assert result.action_needed  # provenance-stamped guidance survives


def test_declared_step_assembles_with_backend():
    spec = RecipeSpec(
        pattern="declared_step",
        params=[
            ParamBinding(param_name="install_steps", row_field="install_steps"),
            ParamBinding(param_name="uninstall_steps", row_field="uninstall_steps"),
            ParamBinding(param_name="verified", literal=True),
        ],
    )
    row = _row(
        recipe_kind=ProviderRecipeKind.HOOKS,
        install_steps=[{"type": "shell", "command": "echo hi"}],
        uninstall_steps=[{"type": "shell", "command": "echo bye"}],
    )
    recipe = assemble_hindsight_recipe(row, _backend(), spec)
    # provision_steps is provided by the DeclaredStepRecipe delegate
    assert recipe.provision_steps()
