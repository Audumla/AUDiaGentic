from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from audiagentic.components.memory.hindsight.declared_integration import (
    DeclaredHindsightIntegrationRecipe,
    DeclaredIntegrationDefinition,
    HindsightIntegrationDesired,
)
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HINDSIGHT_RECIPE_MATRIX
from audiagentic.components.memory.hindsight.strategies import build_hindsight_recipe
from audiagentic.components.providers.services.recipes import RecipeResult, RecipeState


def _row(provider_id: str):
    return next(row for row in HINDSIGHT_RECIPE_MATRIX if row.provider_id == provider_id)


def test_cline_and_aider_config_parse_to_frozen_definitions():
    cline = DeclaredIntegrationDefinition.from_row(_row("cline"))
    aider = DeclaredIntegrationDefinition.from_row(_row("aider"))

    assert cline.provider_id == "cline"
    assert cline.install[0].command == ("pip", "install", "hindsight-cline")
    assert aider.provider_id == "aider"
    assert aider.install[0].command[-2:] == ("hindsight-aider", "aider-chat")


def test_definition_serialization_matches_schema():
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "src/audiagentic/config/components/memory/hindsight-integration-recipe.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(
        DeclaredIntegrationDefinition.from_row(_row("cline")).to_mapping()
    )


def test_recipe_renders_typed_desired_values_without_provider_handler():
    recipe = build_hindsight_recipe(
        _row("cline"),
        HindsightBackendConfig(
            base_url="https://memory.invalid", api_key="secret", bank_id="bank"
        ),
        "cline",
    )
    assert isinstance(recipe, DeclaredHindsightIntegrationRecipe)
    commands = [step.command for step in recipe.provision_steps()]
    assert commands[1] == (
        "hindsight-cline", "install", "--api-url=https://memory.invalid",
        "--api-token=secret", "--bank-id=bank",
    )


def test_install_result_does_not_expose_secret(monkeypatch):
    desired = HindsightIntegrationDesired(
        endpoint_url="https://memory.invalid", api_token="secret", bank_id="bank"
    )
    definition = DeclaredIntegrationDefinition.from_row(_row("cline"))
    recipe = DeclaredHindsightIntegrationRecipe(_row("cline"), definition, desired)
    monkeypatch.setattr(
        "audiagentic.components.memory.hindsight.declared_integration.run_steps",
        lambda *args, **kwargs: RecipeResult.ok(
            RecipeState.INSTALLING, status="integration installer succeeded"
        ),
    )
    result = recipe.install({})
    assert result.success
    assert "secret" not in repr(result)
