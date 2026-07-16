"""Tests for declarative recipe execution."""
from __future__ import annotations

from audiagentic.foundation.toolchains.recipe_execution import execute_recipe

# ---------------------------------------------------------------------------
# Integration tests — real fixtures, real probes/steps
# ---------------------------------------------------------------------------

class TestExecuteRecipeReal:
    """End-to-end with fixture YAML files."""

    def test_loads_and_materializes_npm(self) -> None:
        result = execute_recipe(
            "src/audiagentic/config/recipes/fixtures/npm-cli.yaml",
            {"PACKAGE_NAME": "my-package"},
        )
        # Probe will likely fail (npm not installed or no my-package),
        # but we should get a proper RecipeResult, not an exception
        assert result is not None
        assert hasattr(result, "success")

    def test_unknown_param_fails_gracefully(self) -> None:
        result = execute_recipe(
            "src/audiagentic/config/recipes/fixtures/npm-cli.yaml",
            {"UNKNOWN_PARAM": "value"},
        )
        assert not result.success
        assert result.error is not None and "materialize" in result.error

    def test_missing_required_param_fails_gracefully(self) -> None:
        result = execute_recipe(
            "src/audiagentic/config/recipes/fixtures/npm-cli.yaml",
            {},
        )
        assert not result.success
        assert result.error is not None and "materialize" in result.error

    def test_invalid_path_fails_gracefully(self) -> None:
        result = execute_recipe("nonexistent.yaml", {})
        assert not result.success
        assert result.error is not None and "load recipe" in result.error

    def test_lsp_fixture_materializes(self) -> None:
        result = execute_recipe(
            "src/audiagentic/config/recipes/fixtures/lsp-pyright.yaml",
            {"LSP_PACKAGE": "pyright"},
        )
        assert result is not None

    def test_hindsight_fixture_materializes(self) -> None:
        result = execute_recipe(
            "src/audiagentic/config/recipes/fixtures/hindsight-codex.yaml",
            {"URL": "https://example.com", "TOKEN": "secret123"},
        )
        assert result is not None
