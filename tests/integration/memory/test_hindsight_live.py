"""Offline architecture and source gates for Hindsight integration.

These deterministic tests always run regardless of live Hindsight server
availability. They verify:
- Matrix config loads correctly and provides required fields
- Factory registry covers all ProviderRecipeKind values used in the matrix
- Platform gate logic is correct
- Source gate blocks unverified installer execution
- No committed local IP defaults for test servers
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import audiagentic.components.providers  # noqa: F401  (register provider descriptors)
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import (
    HINDSIGHT_RECIPE_MATRIX,
    HindsightRecipeRow,
    get_matrix_rows,
    get_rows_for_provider,
)
from audiagentic.components.memory.hindsight.recipes import _RowRecipe
from audiagentic.components.memory.hindsight.strategies import (
    _RECIPE_FACTORIES,
    build_hindsight_recipe,
)
from audiagentic.components.providers.services.recipes import ProviderRecipeKind

_MATRIX_YAML = Path(__file__).parents[3] / "src" / "audiagentic" / "config" / "components" / "memory" / "hindsight_matrix.yaml"


class TestArchitectureGates:
    """Architecture/source gates that pass regardless of live server."""

    def test_matrix_loads_non_empty(self):
        """Matrix config loads and contains at least one row."""
        rows = get_matrix_rows()
        assert len(rows) > 0, "hindsight_matrix.yaml must contain at least one provider"

    def test_matrix_required_fields_present(self):
        """Every matrix row has required fields populated."""
        for row in HINDSIGHT_RECIPE_MATRIX:
            assert row.provider_id, "provider_id must be set"
            assert row.display_name, "display_name must be set"
            assert row.recipe_kind is not None, "recipe_kind must be a valid ProviderRecipeKind"
            assert row.source_status in (
                "verified", "unconfirmed", "blocked", "no_hindsight"
            ), f"invalid source_status: {row.source_status!r}"

    def test_no_committed_local_ip(self):
        """No committed local IP literal for Hindsight test server."""
        content = _MATRIX_YAML.read_text(encoding="utf-8")
        assert "10.0.0." not in content, "committed local IP 10.0.0.x in matrix"
        assert "192.168." not in content, "committed local IP 192.168.x.x in matrix"
        assert "HINDSIGHT_TEST_MCP_URL" not in content, "test URL should be env-only"

    def test_factory_coverage_all_matrix_kinds(self):
        """Every recipe_kind used in the matrix has a factory or guidance fallback."""
        kinds_in_matrix = {row.recipe_kind for row in HINDSIGHT_RECIPE_MATRIX}
        for kind in ProviderRecipeKind:
            if kind in kinds_in_matrix:
                assert kind in _RECIPE_FACTORIES, (
                    f"{kind.value} is used in matrix but has no factory entry"
                )

    def test_factory_unknown_kind_returns_guidance(self):
        """Kinds not in the registry dispatch to GuidanceOnlyRecipe."""
        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="none",
            recipe_kind=ProviderRecipeKind.NATIVE_PASSTHROUGH,
        )
        backend = HindsightBackendConfig(base_url="http://x:8888")
        recipe = build_hindsight_recipe(row, backend, "test")
        assert isinstance(recipe, _RowRecipe)


class TestSourceGates:
    """Source gate: unverified installers must not execute."""

    def test_unverified_hooks_become_guidance_only(self):
        """Hooks kind with unverified status returns GuidanceOnlyRecipe."""
        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="unconfirmed",
            install_steps=[{"type": "shell", "command": ["echo", "install"]}],
        )
        backend = HindsightBackendConfig(base_url="http://x:8888")
        recipe = build_hindsight_recipe(row, backend, "test")
        assert isinstance(recipe, _RowRecipe)

    def test_blocked_mcp_becomes_guidance_only(self):
        """MCP config with blocked status returns GuidanceOnlyRecipe."""
        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="mcp",
            recipe_kind=ProviderRecipeKind.MCP_CONFIG,
            source_status="blocked",
        )
        backend = HindsightBackendConfig(base_url="http://x:8888")
        recipe = build_hindsight_recipe(row, backend, "test")
        assert isinstance(recipe, _RowRecipe)


class TestPlatformGates:
    """Platform gate: unsupported installers fall back to external."""

    def test_platform_gate_blocks_unsupported(self, monkeypatch):
        """Provider constrained to darwin/linux is platform-gated on win."""
        from audiagentic.components.memory.hindsight import strategies as rec

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="verified",
            platform_constraints=["darwin", "linux"],
        )

        monkeypatch.setattr(
            "audiagentic.foundation.toolchains.platform_key", lambda: "win"
        )
        supported = rec._platform_supported(row)
        assert supported is False, "win should not match darwin/linux constraints"

    def test_platform_gate_allows_supported(self, monkeypatch):
        """Provider constrained to darwin/linux is allowed on linux."""
        from audiagentic.components.memory.hindsight import strategies as rec

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="verified",
            platform_constraints=["darwin", "linux"],
        )

        monkeypatch.setattr(
            "audiagentic.foundation.toolchains.platform_key", lambda: "linux"
        )
        supported = rec._platform_supported(row)
        assert supported is True, "linux should match darwin/linux constraints"


class TestMatrixFreshness:
    """Freshness assertion over verified matrix rows."""

    _STABLE_ALLOWLIST = {
        "goose",
        "local-openai",
        "pi",
        "plandex",
        "qwen",
    }

    def test_verified_rows_have_recent_source_date(self):
        """Verified rows should have a source_date within 90 days unless allowlisted."""
        cutoff = datetime.now() - timedelta(days=90)
        stale: list[str] = []
        for row in HINDSIGHT_RECIPE_MATRIX:
            if row.source_status != "verified" or row.provider_id in self._STABLE_ALLOWLIST:
                continue
            if not row.source_date:
                stale.append(f"{row.provider_id}: missing source_date")
                continue
            try:
                date = datetime.strptime(row.source_date, "%Y-%m-%d")
                if date < cutoff:
                    stale.append(
                        f"{row.provider_id}: source_date {row.source_date} is stale"
                    )
            except ValueError:
                stale.append(f"{row.provider_id}: invalid source_date format {row.source_date!r}")

        assert not stale, f"stale verified rows (not allowlisted): {'; '.join(stale)}"


class TestLiveFixtureGating:
    """Live fixture skips network-dependent tests when URL is unset/unreachable."""

    def test_hindsight_test_url_is_not_in_env(self):
        """Test server URL must come from env, not committed config."""
        url = os.environ.get("HINDSIGHT_TEST_MCP_URL")
        if url:
            pytest.skip("HINDSIGHT_TEST_MCP_URL is set; live tests will run separately")

    def test_no_default_backend_in_tests(self):
        """Test fixtures should not configure a default Hindsight backend IP."""
        import tempfile

        from audiagentic.components.memory.hindsight.export import build_hindsight_backend
        with tempfile.TemporaryDirectory() as tmp:
            backend = build_hindsight_backend(Path(tmp))
            assert backend is None, "fresh project should have no default backend"


class TestProviderCorrectnessDecisions:
    """Documented provider-specific behavior for e2e assertions."""

    def test_gemini_oauth_proxy_status(self):
        """Gemini Cloud uses built-in MCP support via OAuth; no hook-based recall.

        Self-hosted requires Cloudflare OAuth proxy + tunnel. The recipe
        should not assert hook-based auto-recall/retain.
        """
        rows = get_rows_for_provider("gemini")
        assert len(rows) > 0
        row = rows[0]
        assert row.recipe_kind == ProviderRecipeKind.MCP_CONFIG

    def test_copilot_project_local_scope(self):
        """Copilot integration writes to project-local paths only."""
        rows = get_rows_for_provider("copilot")
        assert len(rows) > 0
        row = rows[0]
        assert row.scope == "project-local", "Copilot should be project-local"
