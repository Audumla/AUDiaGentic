"""Tests for Hindsight strategy resolver and builder (HM03)."""
from __future__ import annotations

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import (
    HindsightRecipeRow,
    get_matrix_rows,
    get_rows_by_kind,
    get_rows_for_provider,
)
from audiagentic.components.memory.hindsight.recipes import GuidanceOnlyRecipe
from audiagentic.components.memory.hindsight.strategies import (
    build_hindsight_recipe,
    resolve_hindsight_strategy,
)
from audiagentic.components.providers.services.recipes import ProviderRecipeKind
from audiagentic.foundation.toolchains.recipe_contract import RecipeState


class TestResolverPrecedence:
    """test_resolver_precedence: explicit > native > mcp-config > fallback-mcp > rules-only."""

    def test_native_provider_resolves_to_native_or_fallback(self):
        row = resolve_hindsight_strategy("codex")
        assert row is not None
        # Codex uses hooks (cross-platform Python stdlib)
        assert row.recipe_kind == ProviderRecipeKind.HOOKS

    def test_mcp_config_provider_resolves_to_mcp(self):
        row = resolve_hindsight_strategy("gemini")
        assert row is not None
        assert row.recipe_kind == ProviderRecipeKind.MCP_CONFIG

    def test_guidance_provider_resolves_to_guidance(self):
        row = resolve_hindsight_strategy("local-openai")
        assert row is not None
        assert row.recipe_kind == ProviderRecipeKind.GUIDANCE_ONLY

    def test_unknown_provider_returns_none(self):
        row = resolve_hindsight_strategy("nonexistent_provider")
        assert row is None


class TestPlatformGate:
    """test_platform_gate: cline/codex (platforms=linux,darwin) on win resolve to fallback."""

    def test_cline_platform_constraints(self):
        # Cline is darwin/linux only; on win it falls back to MCP config
        row = resolve_hindsight_strategy("cline")
        assert row is not None
        import sys
        if sys.platform.startswith("win"):
            # Platform gate triggers fallback to MCP config
            assert row.recipe_kind == ProviderRecipeKind.MCP_CONFIG
            assert "platform-gated" in row.notes
        else:
            assert row.recipe_kind == ProviderRecipeKind.HOOKS
            assert "darwin" in row.platform_constraints
            assert "linux" in row.platform_constraints

    def test_codex_cross_platform(self):
        # Codex hooks are pure Python stdlib, work on all platforms
        row = resolve_hindsight_strategy("codex")
        assert row is not None
        assert row.recipe_kind == ProviderRecipeKind.HOOKS
        # Platform constraints use canonical keys (darwin/linux/win)
        assert "darwin" in row.platform_constraints
        assert "linux" in row.platform_constraints
        assert "win" in row.platform_constraints


class TestSourceGate:
    """test_source_gate: native/launch-wrapper specs with source_status!='verified' cannot execute."""

    def test_verified_native_allows_execution(self):
        # Codex is now verified — hooks recipe should be executable
        row = resolve_hindsight_strategy("codex")
        if row and row.recipe_kind in (ProviderRecipeKind.HOOKS, ProviderRecipeKind.WRAPPER_CLI):
            assert row.source_status == "verified"

    def test_guidance_recipe_for_unverified(self):
        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="unconfirmed",
            audia_action="call_official_installer",
        )

        backend = HindsightBackendConfig(base_url="http://test")
        recipe = build_hindsight_recipe(row, backend, "test")
        assert isinstance(recipe, GuidanceOnlyRecipe)


class TestBuilder:
    """test_builder: produces correct recipe types for each strategy kind."""

    def test_builder_mcp_config_creates_adapter(self):

        row = HindsightRecipeRow(
            provider_id="gemini",
            display_name="Gemini",
            integration_type="mcp",
            recipe_kind=ProviderRecipeKind.MCP_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        backend = HindsightBackendConfig(base_url="http://test")
        recipe = build_hindsight_recipe(row, backend, "gemini")
        assert recipe is not None
        assert recipe.provider_id == "gemini"

    def test_builder_guidance_only(self):

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="rules-only",
            recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
            audia_action="action_needed",
        )
        backend = HindsightBackendConfig(base_url="http://test")
        recipe = build_hindsight_recipe(row, backend, "test")
        # GUIDANCE_ONLY is now assembled via RecipeSpec; verify behaviour, not class
        result = recipe.probe({})
        assert result.state == RecipeState.ABSENT


class TestParameterizeCommand:
    """test_parameterize_command: replaces brace-delimited placeholders with backend values."""

    def test_replaces_url(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command

        backend = HindsightBackendConfig(base_url="http://localhost:8888")
        cmd = "hindsight-cline install --api-url {URL} --api-token {KEY}"
        result = _parameterize_command(cmd, backend)
        assert "http://localhost:8888" in result

    def test_replaces_token_and_key(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command

        backend = HindsightBackendConfig(
            base_url="http://localhost:8888",
            api_key="sk-test-key",
        )
        cmd = "hindsight-copilot init --api-token {TOKEN} --bank-id {ID}"
        result = _parameterize_command(cmd, backend)
        assert "sk-test-key" in result

    def test_replaces_bank_id(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command

        backend = HindsightBackendConfig(
            base_url="http://localhost:8888",
            api_key="sk-test-key",
            bank_id="my-bank",
        )
        cmd = "hindsight-openhands init --api-token {TOKEN} --bank-id {ID}"
        result = _parameterize_command(cmd, backend)
        assert "my-bank" in result

    def test_empty_command_returns_empty(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command

        backend = HindsightBackendConfig(base_url="http://localhost:8888")
        result = _parameterize_command("", backend)
        assert result == ""

    def test_literal_ident_not_corrupted(self):
        """Brace-delimited format does not corrupt commands containing bare words like IDENT."""
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command

        backend = HindsightBackendConfig(
            base_url="http://localhost:8888",
            api_key="sk-test-key",
            bank_id="my-bank",
        )
        cmd = "some-command --check IDENT status"
        result = _parameterize_command(cmd, backend)
        assert "IDENT" in result
        assert result == "some-command --check IDENT status"


class TestMatrix:
    """Matrix has expected providers and can be filtered."""

    def test_matrix_has_rows(self):
        rows = get_matrix_rows()
        assert len(rows) >= 4

    def test_matrix_by_provider(self):
        rows = get_rows_for_provider("codex")
        assert len(rows) == 1
        assert rows[0].provider_id == "codex"

    def test_matrix_by_kind(self):
        mcp_rows = get_rows_by_kind(ProviderRecipeKind.MCP_CONFIG)
        assert len(mcp_rows) >= 1

        hybrid_rows = get_rows_by_kind(ProviderRecipeKind.HYBRID)
        assert len(hybrid_rows) >= 1


class TestHM10Validation:
    """Deletion-proof and regression tests for HM10 cleanup."""

    def test_recipe_kind_map_deleted(self):
        """_RECIPE_KIND_MAP no longer exists in matrix module namespace."""
        from audiagentic.components.memory.hindsight import matrix as matrix_module

        assert not hasattr(matrix_module, "_RECIPE_KIND_MAP")

    def test_desired_mcp_entry_deleted(self):
        """_desired_mcp_entry no longer exists in mcp_recipe module namespace."""
        from audiagentic.components.memory.hindsight import mcp_recipe

        assert not hasattr(mcp_recipe, "_desired_mcp_entry")

    def test_mcp_recipe_module_has_no_recipe_classes(self):
        """SL13 A4: mcp_recipe.py reduced to payload builders; no recipe classes remain."""
        from audiagentic.components.memory.hindsight import mcp_recipe

        assert not hasattr(mcp_recipe, "HindsightMcpRecipe")
        assert not hasattr(mcp_recipe, "HindsightTarget")
        # Only payload builder functions should be public
        assert hasattr(mcp_recipe, "build_hindsight_entry")
        assert hasattr(mcp_recipe, "build_hindsight_mcp_entry")

    def test_invalid_recipe_kind_fallback(self):
        """Invalid recipe kind falls back to GUIDANCE_ONLY without raising."""
        import tempfile
        from pathlib import Path

        import yaml

        from audiagentic.components.memory.hindsight.matrix import _load_matrix

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "test_matrix.yaml"
            config_path.write_text(
                yaml.dump({
                    "matrix": [
                        {
                            "provider_id": "test",
                            "display_name": "Test",
                            "integration_type": "unknown",
                            "recipe_kind": "invalid_unknown_kind",
                        }
                    ]
                }),
                encoding="utf-8",
            )
            original = None
            try:
                import audiagentic.components.memory.hindsight.matrix as matrix_module

                original = getattr(matrix_module, "_CONFIG_PATH", None)
                matrix_module._CONFIG_PATH = config_path

                rows = _load_matrix()
                assert len(rows) == 1
                assert rows[0].recipe_kind == ProviderRecipeKind.GUIDANCE_ONLY
            finally:
                if original is not None:
                    import audiagentic.components.memory.hindsight.matrix as matrix_module

                    matrix_module._CONFIG_PATH = original

    def test_build_hindsight_mcp_entry_stdio(self):
        """McpServerEntry built directly from backend for stdio transport."""
        from audiagentic.components.memory.hindsight.mcp_recipe import build_hindsight_mcp_entry

        backend = HindsightBackendConfig(
            base_url="http://localhost:8888",
            transport="stdio",
            api_key="sk-test",
            bank_id="my-bank",
        )
        entry = build_hindsight_mcp_entry(backend)
        assert entry.command == "hindsight-mcp"
        assert "--base-url" in entry.args
        assert entry.env.get("HINDSIGHT_API_KEY") == "sk-test"
        assert entry.env.get("HINDSIGHT_BANK_ID") == "my-bank"

    def test_build_hindsight_mcp_entry_http(self):
        """McpServerEntry built directly from backend for HTTP transport."""
        from audiagentic.components.memory.hindsight.mcp_recipe import build_hindsight_mcp_entry

        backend = HindsightBackendConfig(
            base_url="http://localhost:8888",
            transport="http",
            api_key="sk-test",
        )
        entry = build_hindsight_mcp_entry(backend)
        assert entry.url == "http://localhost:8888/mcp"
        assert entry.headers.get("Authorization") == "Bearer sk-test"


class TestHM11Validation:
    """Deletion-proof tests for HM11 lifecycle cleanup."""

    def test_run_provision_deleted(self):
        """_run_provision no longer exists in recipes module namespace."""
        from audiagentic.components.memory.hindsight import recipes

        assert not hasattr(recipes, "_run_provision")

    def test_run_teardown_deleted(self):
        """_run_teardown no longer exists in recipes module namespace."""
        from audiagentic.components.memory.hindsight import recipes

        assert not hasattr(recipes, "_run_teardown")

    def test_reconcile_exists(self):
        """_reconcile helper exists and is callable (lifecycle module post-split)."""
        from audiagentic.components.memory.hindsight import lifecycle

        assert callable(getattr(lifecycle, "_reconcile", None))

    def test_row_recipe_is_capability_recipe(self):
        """_RowRecipe subclasses ProviderCapabilityRecipe."""
        from audiagentic.components.memory.hindsight.recipes import _RowRecipe
        from audiagentic.components.providers.services.recipes import (
            ProviderCapabilityRecipe,
        )

        assert issubclass(_RowRecipe, ProviderCapabilityRecipe)

    def test_row_recipe_uses_base_orchestration(self):
        """_RowRecipe inherits provision/teardown from the base contract (HM20).

        Orchestration lives once in ProvisioningRecipe; hindsight overlays
        provenance solely via to_result, and execution stays on the primitive
        path (provision_steps() is introspection-only for these recipes).
        """
        from audiagentic.components.memory.hindsight.recipes import _RowRecipe

        assert "provision" not in _RowRecipe.__dict__
        assert "teardown" not in _RowRecipe.__dict__
        assert "to_result" in _RowRecipe.__dict__
        assert _RowRecipe.provision_via_steps is False
