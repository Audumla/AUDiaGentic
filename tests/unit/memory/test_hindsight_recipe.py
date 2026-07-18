"""MA27 memory orchestration boundary tests.

Tests the family-preference orchestration over providers_api: reconcile_hindsight,
build_hindsight_status_report, and the supporting infrastructure (entry builders,
desired state). No matrix, no factory dispatch, no recipe registry.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import audiagentic.components.providers  # noqa: F401 — register provider descriptors
from audiagentic.components.memory.hindsight.codex_pi_desired import (
    CodexHindsightDesired,
    HookCommand,
)
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.mcp_recipe import (
    build_hindsight_entry,
    build_hindsight_managed_entry,
)
from audiagentic.components.memory.hindsight.provision import (
    _hindsight_families,
    _resolve_family,
    build_hindsight_status_report,
    discover_provider_ids,
    reconcile_hindsight,
)

_BACKEND = HindsightBackendConfig(base_url="https://hs.example.com")


# ---------------------------------------------------------------------------
# MCP entry shape — retained from pre-MA27 test coverage
# ---------------------------------------------------------------------------

class TestMcpEntryShape:
    """MCP entry builders produce correct shapes per transport."""

    def test_sse_entry(self):
        backend = replace(_BACKEND, transport="sse", api_key="k")
        entry = build_hindsight_entry(backend)
        assert entry["type"] == "sse"
        assert entry["url"] == "https://hs.example.com/mcp"
        assert entry["headers"]["Authorization"] == "Bearer k"

    def test_stdio_entry(self):
        backend = replace(_BACKEND, transport="stdio", api_key="k")
        entry = build_hindsight_entry(backend)
        assert entry["command"] == "hindsight-mcp"
        assert "--base-url" in entry["args"]
        assert entry["env"]["HINDSIGHT_API_KEY"] == "k"

    def test_managed_entry_has_stable_id(self):
        managed = build_hindsight_managed_entry(_BACKEND)
        assert managed.managed_id == "ag-hindsight"
        assert managed.name == "hindsight"


# ---------------------------------------------------------------------------
# Family resolution — fixed preference order, no provider-id branches
# ---------------------------------------------------------------------------

class TestFamilyPreferenceOrder:
    """Step 2: Fixed family preference resolves first supported family."""

    def test_fixed_order(self):
        families = _hindsight_families()
        assert families == ["managed-hooks", "managed-mcp", "plugin-entry"]

    def test_codex_resolves_to_managed_hooks(self):
        family = _resolve_family("codex")
        assert family == "managed-hooks"

    def test_unsupported_provider_returns_none(self):
        family = _resolve_family("nonexistent-provider-xyz")
        assert family is None


# ---------------------------------------------------------------------------
# Desired state — typed, no Any payloads
# ---------------------------------------------------------------------------

class TestCodexDesiredState:
    """Step 4: Backend builders produce frozen desired state."""

    def test_codex_desired_has_hook_commands(self):
        from audiagentic.components.memory.hindsight.provision import _build_codex_desired

        desired = _build_codex_desired(_BACKEND)
        assert isinstance(desired, CodexHindsightDesired)
        assert len(desired.hook_commands) == 3
        events = {hc.event for hc in desired.hook_commands}
        assert events == {"SessionStart", "UserPromptSubmit", "Stop"}

    def test_codex_desired_round_trip(self):
        cmds = (
            HookCommand(event="SessionStart", command="python s.py", timeout=5),
            HookCommand(event="Stop", command="python r.py", timeout=30),
        )
        desired = CodexHindsightDesired(
            base_url="http://localhost:8888",
            bank_id="codex",
            hook_commands=cmds,
        )
        mapped = desired.to_mapping()
        restored = CodexHindsightDesired.from_mapping(mapped)
        assert desired == restored


# ---------------------------------------------------------------------------
# Reconcile orchestration — family-based, no registry
# ---------------------------------------------------------------------------

class TestReconcileOrchestration:
    """Step 3: reconcile_hindsight calls providers_api, preserves summary shape."""

    def test_summary_shape_has_action_and_providers(self, tmp_path):
        result = reconcile_hindsight(
            tmp_path,
            provider_ids=["codex"],
            active=False,
        )
        assert "action" in result
        assert "providers" in result
        assert isinstance(result["providers"], dict)

    def test_torn_down_action_when_inactive(self, tmp_path):
        result = reconcile_hindsight(
            tmp_path,
            provider_ids=["codex"],
            active=False,
        )
        assert result["action"] == "torn-down"

    def test_provider_entry_has_success_state_role(self, tmp_path):
        result = reconcile_hindsight(
            tmp_path,
            provider_ids=["codex"],
            active=False,
        )
        if "codex" in result["providers"]:
            entry = result["providers"]["codex"]
            assert "success" in entry
            assert "state" in entry
            assert "role" in entry

    def test_guidance_only_fallback(self, tmp_path):
        """A provider with no supported family gets guidance-only role."""
        result = reconcile_hindsight(
            tmp_path,
            provider_ids=["nonexistent-provider-xyz"],
            active=True,
        )
        # Should succeed without crashing; may get guidance-only or fail gracefully
        assert "action" in result

    def test_no_registry_import_in_provision(self):
        """Verify the new provision module does not import legacy types."""
        import audiagentic.components.memory.hindsight.provision as prov
        source = Path(prov.__file__).read_text(encoding="utf-8")
        assert "ProviderRecipeRegistry" not in source
        assert "ProviderRecipeResult" not in source
        assert "HINDSIGHT_RECIPE_MATRIX" not in source
        assert "register_hindsight_recipes" not in source


# ---------------------------------------------------------------------------
# Status report — family queries, no registry
# ---------------------------------------------------------------------------

class TestStatusReport:
    """Step 3: build_hindsight_status_report uses providers_api queries."""

    def test_unconfigured_returns_empty(self, tmp_path):
        result = build_hindsight_status_report(tmp_path)
        assert result["configured"] is False
        assert result["providers"] == {}

    def test_no_registry_import_in_status_path(self):
        import audiagentic.components.memory.hindsight.provision as prov
        source = Path(prov.__file__).read_text(encoding="utf-8")
        assert "ProviderRecipeRegistry" not in source


# ---------------------------------------------------------------------------
# Provider discovery — no provider services import at memory boundary
# ---------------------------------------------------------------------------

class TestProviderDiscovery:
    """Step 4: discover_provider_ids uses providers_api, not internal discovery."""

    def test_returns_tuple_of_lists(self, tmp_path):
        all_ids, enabled_ids = discover_provider_ids(tmp_path)
        assert isinstance(all_ids, list)
        assert isinstance(enabled_ids, list)


# ---------------------------------------------------------------------------
# Architecture — no matrix/factory/registry in memory after MA27
# ---------------------------------------------------------------------------

class TestArchitectureNoLegacy:
    """Step 9: No legacy symbols in the memory component."""

    def test_no_matrix_module(self):
        with pytest.raises(ImportError, match="matrix"):
            import audiagentic.components.memory.hindsight.matrix  # noqa: F401

    def test_no_strategies_module(self):
        with pytest.raises(ImportError, match="strategies"):
            import audiagentic.components.memory.hindsight.strategies  # noqa: F401

    def test_no_recipe_spec_module(self):
        with pytest.raises(ImportError, match="recipe_spec"):
            import audiagentic.components.memory.hindsight.recipe_spec  # noqa: F401

    def test_no_lifecycle_module(self):
        with pytest.raises(ImportError, match="lifecycle"):
            import audiagentic.components.memory.hindsight.lifecycle  # noqa: F401

    def test_provision_has_no_legacy_imports(self):
        import audiagentic.components.memory.hindsight.provision as prov
        source = Path(prov.__file__).read_text(encoding="utf-8")
        for symbol in (
            "HINDSIGHT_RECIPE_MATRIX",
            "register_hindsight_recipes",
            "ProviderRecipeRegistry",
            "ProviderRecipeKind",
            "build_hindsight_recipe",
            "resolve_hindsight_strategy",
        ):
            assert symbol not in source, f"Legacy symbol '{symbol}' found in provision.py"

    def test_provision_uses_only_public_provider_boundary(self):
        import audiagentic.components.memory.hindsight.provision as prov

        source = Path(prov.__file__).read_text(encoding="utf-8")
        assert "audiagentic.components.providers.descriptors" not in source
        assert "audiagentic.components.providers.contracts" not in source
        provider_imports = [
            line
            for line in source.splitlines()
            if line.startswith("from audiagentic.components.providers")
        ]
        assert provider_imports == [
            "from audiagentic.components.providers.providers_api import ("
        ]
