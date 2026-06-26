"""Tests for Hindsight strategy resolver and builder (HM03)."""
from __future__ import annotations

from audiagentic.components.memory.hindsight.matrix import (
    HindsightRecipeRow,
    get_matrix_rows,
    get_rows_by_kind,
    get_rows_for_provider,
)
from audiagentic.components.memory.hindsight.recipes import (
    GuidanceOnlyRecipe,
    resolve_hindsight_strategy,
)
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
)


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
        row = resolve_hindsight_strategy("windsurf")
        assert row is not None
        assert row.recipe_kind in (ProviderRecipeKind.HYBRID, ProviderRecipeKind.GUIDANCE_ONLY)

    def test_unknown_provider_returns_none(self):
        row = resolve_hindsight_strategy("nonexistent_provider")
        assert row is None


class TestPlatformGate:
    """test_platform_gate: cline/codex (platforms=linux,darwin) on win resolve to fallback."""

    def test_cline_platform_constraints(self):
        # Cline is macOS/Linux only; on Windows it falls back to MCP config
        row = resolve_hindsight_strategy("cline")
        assert row is not None
        import sys
        if sys.platform.startswith("win"):
            # Platform gate triggers fallback to MCP config
            assert row.recipe_kind == ProviderRecipeKind.MCP_CONFIG
            assert "platform-gated" in row.notes
        else:
            assert row.recipe_kind == ProviderRecipeKind.HOOKS
            assert "macOS" in row.platform_constraints
            assert "Linux" in row.platform_constraints

    def test_codex_cross_platform(self):
        # Codex hooks are pure Python stdlib, work on all platforms
        row = resolve_hindsight_strategy("codex")
        assert row is not None
        assert row.recipe_kind == ProviderRecipeKind.HOOKS
        # Platform constraints include all three
        assert "macOS" in row.platform_constraints
        assert "Linux" in row.platform_constraints
        assert "Windows" in row.platform_constraints


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
        from audiagentic.components.memory.hindsight.recipes import build_hindsight_recipe
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig

        backend = HindsightBackendConfig(base_url="http://test")
        recipe = build_hindsight_recipe(row, backend, "test")
        assert isinstance(recipe, GuidanceOnlyRecipe)


class TestBuilder:
    """test_builder: produces correct recipe types for each strategy kind."""

    def test_builder_mcp_config_creates_adapter(self):
        from audiagentic.components.memory.hindsight.recipes import build_hindsight_recipe
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig

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
        from audiagentic.components.memory.hindsight.recipes import build_hindsight_recipe
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="rules-only",
            recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
            audia_action="action_needed",
        )
        backend = HindsightBackendConfig(base_url="http://test")
        recipe = build_hindsight_recipe(row, backend, "test")
        assert isinstance(recipe, GuidanceOnlyRecipe)


class TestParameterizeCommand:
    """test_parameterize_command: replaces placeholders with backend values."""

    def test_replaces_url(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig

        backend = HindsightBackendConfig(base_url="http://localhost:8888")
        cmd = "hindsight-cline install --api-url URL --api-token KEY"
        result = _parameterize_command(cmd, backend)
        assert "http://localhost:8888" in result

    def test_replaces_token_and_key(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig

        backend = HindsightBackendConfig(
            base_url="http://localhost:8888",
            api_key="sk-test-key",
        )
        cmd = "hindsight-copilot init --api-token TOKEN --bank-id ID"
        result = _parameterize_command(cmd, backend)
        assert "sk-test-key" in result

    def test_replaces_bank_id(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig

        backend = HindsightBackendConfig(
            base_url="http://localhost:8888",
            api_key="sk-test-key",
            bank_id="my-bank",
        )
        cmd = "hindsight-openhands init --api-token TOKEN --bank-id ID"
        result = _parameterize_command(cmd, backend)
        assert "my-bank" in result

    def test_empty_command_returns_empty(self):
        from audiagentic.components.memory.hindsight.recipes import _parameterize_command
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig

        backend = HindsightBackendConfig(base_url="http://localhost:8888")
        result = _parameterize_command("", backend)
        assert result == ""


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
