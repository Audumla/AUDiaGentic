"""Regression test: every strategy kind must provision through ProviderRecipeRegistry.

This test exists to catch latent crashes in recipe lifecycle paths that goldens
miss because they exercise old classes directly. SL16 (RV169) discovered that the
assembler's _SpecDrivenRecipe.provision() raised NotImplementedError for declared_step,
which would have crashed apply_hindsight for any HOOKS/WRAPPER_CLI provider — but
the full unit suite passed because only goldens were run.

After revert: direct class instantiation must pass through registry lifecycle without exception.
"""
from __future__ import annotations

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.strategies import build_hindsight_recipe
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeRegistry,
)


class TestRegistryProvision:
    """Every strategy kind must provision through registry without crashing.

    This is the single test whose absence hid the SL15 crash (RV169). It exercises
    the full probe→install→configure→verify lifecycle via registry.install().
    """

    def _make_backend(self) -> HindsightBackendConfig:
        return HindsightBackendConfig(
            base_url="http://localhost:8888",
            server_name="test-hindsight",
            transport="stdio",
        )

    def test_guidance_only_provision_through_registry(self):
        """GUIDANCE_ONLY recipe provisions without crash."""
        row = HindsightRecipeRow(
            provider_id="test-guidance",
            display_name="Test Guidance",
            integration_type="guidance-only",
            recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
            audia_action="action_needed",
        )
        backend = self._make_backend()
        recipe = build_hindsight_recipe(row, backend, "test-guidance")

        registry = ProviderRecipeRegistry()
        registry.register(recipe)
        result = registry.install("test-guidance", "hindsight")
        assert result is not None

    def test_hooks_verified_provision_through_registry(self):
        """HOOKS (verified) recipe provisions without crash."""
        row = HindsightRecipeRow(
            provider_id="test-hooks",
            display_name="Test Hooks",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="verified",
            audia_action="call_official_installer",
            install_steps=[{"type": "shell", "command": "echo test"}],
            uninstall_steps=[{"type": "shell", "command": "echo uninstall"}],
        )
        backend = self._make_backend()
        recipe = build_hindsight_recipe(row, backend, "test-hooks")

        registry = ProviderRecipeRegistry()
        registry.register(recipe)
        # Should not raise NotImplementedError (the RV169 crash)
        result = registry.install("test-hooks", "hindsight")
        assert result is not None

    def test_hooks_unverified_falls_back_to_guidance(self):
        """HOOKS (unverified) falls back to guidance-only, no crash."""
        row = HindsightRecipeRow(
            provider_id="test-hooks-unverified",
            display_name="Test Hooks Unverified",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="unconfirmed",
            audia_action="call_official_installer",
        )
        backend = self._make_backend()
        recipe = build_hindsight_recipe(row, backend, "test-hooks-unverified")

        registry = ProviderRecipeRegistry()
        registry.register(recipe)
        result = registry.install("test-hooks-unverified", "hindsight")
        assert result is not None

    def test_wrapper_cli_provision_through_registry(self):
        """WRAPPER_CLI recipe provisions without crash."""
        row = HindsightRecipeRow(
            provider_id="test-wrapper",
            display_name="Test Wrapper CLI",
            integration_type="wrapper-cli",
            recipe_kind=ProviderRecipeKind.WRAPPER_CLI,
            source_status="verified",
            audia_action="call_official_installer",
            install_steps=[{"type": "shell", "command": "echo wrapper"}],
        )
        backend = self._make_backend()
        recipe = build_hindsight_recipe(row, backend, "test-wrapper")

        registry = ProviderRecipeRegistry()
        registry.register(recipe)
        result = registry.install("test-wrapper", "hindsight")
        assert result is not None

    def test_rules_only_probe_does_not_crash(self):
        """RulesOnly recipe probe works through registry status()."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Test\n")
            rule_path = f.name

        try:
            row = HindsightRecipeRow(
                provider_id="test-rules",
                display_name="Test Rules",
                integration_type="rules-only",
                recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
                audia_action="action_needed",
            )
            backend = self._make_backend()
            recipe = build_hindsight_recipe(row, backend, "test-rules")

            registry = ProviderRecipeRegistry()
            registry.register(recipe)
            status = registry.status("test-rules", "hindsight")
            assert status is not None
        finally:
            Path(rule_path).unlink(missing_ok=True)
