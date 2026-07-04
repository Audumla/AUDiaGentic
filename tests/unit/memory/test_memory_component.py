"""Tests for the memory component — descriptor loading, implementation selection,
config validation, and dynamic contributions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.features.registry import (
    clear as clear_features,
)
from audiagentic.foundation.features.registry import (
    get_implementation,
)
from audiagentic.foundation.features.state import get_implementation_state


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Clear feature registry before each test to avoid cross-test pollution."""
    clear_features()
    register_all_components()
    yield
    clear_features()


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project root with .audiagentic/ directory."""
    (tmp_path / ".audiagentic" / "config" / "runtime" / "features").mkdir(
        parents=True, exist_ok=True
    )
    return tmp_path


class TestDescriptorLoading:
    """Test that memory component and hindsight implementation load correctly."""

    def test_memory_component_loads(self, project_root: Path) -> None:
        from audiagentic.foundation.components.registry import get_descriptor

        desc = get_descriptor("memory")
        assert desc is not None
        assert desc.component_id == "memory"
        assert desc.implementation_cardinality == "exclusive"

    def test_hindsight_implementation_loads(self, project_root: Path) -> None:
        impl = get_implementation("memory", "hindsight")
        assert impl is not None
        assert impl.implementation_id == "hindsight"
        assert impl.raw.get("default") is True

    def test_hindsight_has_options_schema(self, project_root: Path) -> None:
        impl = get_implementation("memory", "hindsight")
        assert impl is not None
        schema = impl.options_schema
        assert "host" in schema
        assert schema["host"].required is True
        assert "port" in schema
        assert schema["port"].default == 8888
        assert "timeout-seconds" in schema
        assert schema["timeout-seconds"].default == 30

    def test_hindsight_has_no_provider_matrix(self, project_root: Path) -> None:
        """Provider matrix is implementation code, not descriptor config."""
        impl = get_implementation("memory", "hindsight")
        assert impl is not None
        assert "provider-matrix" not in impl.raw


class TestImplementationSelection:
    """Test implementation selection and state persistence."""

    def test_default_implementation_is_hindsight(self, project_root: Path) -> None:
        """When no implementation is enabled, the default (hindsight) is returned."""
        from audiagentic.foundation.features.registry import resolve_active_implementation

        active = resolve_active_implementation(project_root, "memory")
        assert active == "hindsight"

    def test_enable_implementation_persists(self, project_root: Path) -> None:
        """Enabling an implementation updates the component state shard."""
        from audiagentic.foundation.features.lifecycle import enable_implementation

        result = enable_implementation(project_root, "memory", "hindsight")
        assert result.get("ok") is True
        assert result.get("implementation") == "hindsight"

        # Verify persisted state
        state = get_implementation_state(project_root, "memory", "hindsight")
        assert state.enabled is True

    def test_exclusive_cardinality_disables_others(self, project_root: Path) -> None:
        """With exclusive cardinality, enabling one disables others."""
        from audiagentic.foundation.features.lifecycle import enable_implementation

        # Enable hindsight first
        enable_implementation(project_root, "memory", "hindsight")
        state = get_implementation_state(project_root, "memory", "hindsight")
        assert state.enabled is True


class TestConfigValidation:
    """Test config get/set with schema validation."""

    def test_get_config_returns_defaults(self, project_root: Path) -> None:
        """Config for an unconfigured implementation returns schema defaults."""
        from audiagentic.components.memory.memory_api import memory_get_config

        # Enable hindsight first
        from audiagentic.foundation.features.lifecycle import enable_implementation
        enable_implementation(project_root, "memory", "hindsight")

        result = memory_get_config(project_root, "hindsight")
        assert result["implementation"] == "hindsight"
        assert result["config"].get("timeout-seconds") == 30

    def test_get_config_exposes_option_schema(self, project_root: Path) -> None:
        """Schema lets callers discover implementation-specific keys generically,
        so the memory MCP surface needs no implementation-specific tools."""
        from audiagentic.components.memory.memory_api import memory_get_config
        from audiagentic.foundation.features.lifecycle import enable_implementation

        enable_implementation(project_root, "memory", "hindsight")

        result = memory_get_config(project_root, "hindsight")
        assert "bank-id" in result["schema"]
        assert "api-key" in result["schema"]
        assert result["schema"]["bank-id"]["type"] == "string"
        assert "description" in result["schema"]["bank-id"]
        assert result["is_default"] is True

    def test_set_config_validates_type(self, project_root: Path) -> None:
        """Setting a config value with wrong type raises validation error."""
        from audiagentic.components.memory.memory_api import memory_set_config
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        with pytest.raises(AudiaGenticError, match="VAL-MEM"):
            memory_set_config(project_root, "hindsight", {"timeout-seconds": "not-an-int"})

    def test_set_config_validates_range(self, project_root: Path) -> None:
        """Setting a config value outside range raises validation error."""
        from audiagentic.components.memory.memory_api import memory_set_config
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        with pytest.raises(AudiaGenticError, match="VAL-MEM"):
            memory_set_config(project_root, "hindsight", {"timeout-seconds": 0})

    def test_set_config_persists(self, project_root: Path) -> None:
        """Setting config values persists them and returns updated config."""
        from audiagentic.components.memory.memory_api import memory_set_config

        result = memory_set_config(project_root, "hindsight", {
            "host": "10.10.100.10",
        })
        assert result["implementation"] == "hindsight"
        assert result["config"]["host"] == "10.10.100.10"
        assert "host" in result["updated_keys"]


class TestMemoryStatus:
    """Test memory_status output contract — memory-owned facts only."""

    def test_status_with_no_config(self, project_root: Path) -> None:
        """Status returns configured=False and surfaces the missing required option."""
        from audiagentic.components.memory.memory_api import memory_status

        result = memory_status(project_root).to_dict()
        assert result["active_implementation"] == "hindsight"
        assert result["configured"] is False
        # Schema-driven guidance: the required host is reported as missing.
        missing = {m["option"]: m["description"] for m in result["missing_required"]}
        assert "host" in missing
        assert missing["host"], "missing option should carry its description for CLI guidance"
        # No provider-specific fields
        assert "provider_support" not in result
        assert "unsupported_providers" not in result

    def test_status_only_optional_option_still_unconfigured(self, project_root: Path) -> None:
        """Setting only an optional option must NOT flip configured to true.

        Regression guard against the old `enabled or options` heuristic, which
        treated any non-empty options as configured regardless of required fields.
        """
        from audiagentic.components.memory.memory_api import (
            memory_set_config,
            memory_status,
        )

        memory_set_config(project_root, "hindsight", {"timeout-seconds": 15})
        result = memory_status(project_root).to_dict()
        assert result["configured"] is False
        assert "host" in [m["option"] for m in result["missing_required"]]

    def test_status_with_config(self, project_root: Path) -> None:
        """Status returns configured=True when the required option is set."""
        from audiagentic.components.memory.memory_api import (
            memory_set_config,
            memory_status,
        )

        memory_set_config(project_root, "hindsight", {
            "host": "10.10.100.10",
        })
        result = memory_status(project_root).to_dict()
        assert result["configured"] is True
        assert result["missing_required"] == []

    def test_status_reports_whether_active_implementation_is_the_default(self, project_root: Path) -> None:
        """details.implementation.is_default distinguishes 'active because selected'
        from 'active because it's the only/default implementation and nothing was
        explicitly enabled' — this was previously invisible outside list_implementations."""
        from audiagentic.components.memory.memory_api import memory_status

        result = memory_status(project_root).to_dict()
        assert result["details"]["implementation"]["is_default"] is True


class TestBoundaryExports:
    """Test that memory exports state/config only."""

    def test_no_dynamic_surface_contribution_api(self) -> None:
        """Memory must not render provider surface content."""
        import audiagentic.components.memory.memory_api as memory_api

        assert not hasattr(memory_api, "build_memory_contributions")

    def test_set_config_returns_refresh_hint(self, project_root: Path) -> None:
        """Providers may use the neutral refresh hint to reconcile themselves."""
        from audiagentic.components.memory.memory_api import memory_set_config

        result = memory_set_config(project_root, "hindsight", {
            "host": "10.10.100.10",
        })
        assert result["needs_provider_recipe_refresh"] is True


class TestIdempotentApply:
    """Test that repeated config apply is idempotent."""

    def test_repeated_set_config_is_idempotent(self, project_root: Path) -> None:
        """Setting the same config twice yields no extra drift."""
        from audiagentic.components.memory.memory_api import memory_set_config

        updates = {"host": "10.10.100.10"}
        result1 = memory_set_config(project_root, "hindsight", updates)
        result2 = memory_set_config(project_root, "hindsight", updates)

        assert result1["config"] == result2["config"]


class TestBackendUrlComposition:
    """Backend base_url is composed from host/port/scheme with sensible defaults."""

    def test_host_only_uses_default_port_and_scheme(self, project_root: Path) -> None:
        from audiagentic.components.memory.hindsight.export import build_hindsight_backend
        from audiagentic.components.memory.memory_api import memory_set_config

        memory_set_config(project_root, "hindsight", {"host": "10.10.100.10"})
        backend = build_hindsight_backend(project_root)
        assert backend is not None
        assert backend.base_url == "http://10.10.100.10:8888"
        assert backend.mcp_url == "http://10.10.100.10:8888/mcp"

    def test_custom_port_and_scheme_override_defaults(self, project_root: Path) -> None:
        from audiagentic.components.memory.hindsight.export import build_hindsight_backend
        from audiagentic.components.memory.memory_api import memory_set_config

        memory_set_config(
            project_root, "hindsight",
            {"host": "hindsight.example.com", "port": 443, "scheme": "https"},
        )
        backend = build_hindsight_backend(project_root)
        assert backend is not None
        assert backend.base_url == "https://hindsight.example.com:443"

    def test_legacy_base_url_option_is_honored(self, project_root: Path) -> None:
        """Existing configs that stored a full base-url keep working (read-time fallback)."""
        from audiagentic.components.memory.hindsight.export import build_hindsight_backend
        from audiagentic.foundation.features.base import ImplementationState
        from audiagentic.foundation.features.state import set_implementation_state

        # Persist a legacy option directly (schema no longer advertises base-url).
        set_implementation_state(
            project_root, "memory", "hindsight",
            ImplementationState(enabled=True, options={"base-url": "http://10.10.100.10:8888"}),
        )
        backend = build_hindsight_backend(project_root)
        assert backend is not None
        assert backend.base_url == "http://10.10.100.10:8888"

    def test_no_host_and_no_base_url_yields_no_backend(self, project_root: Path) -> None:
        from audiagentic.components.memory.hindsight.export import build_hindsight_backend
        from audiagentic.components.memory.memory_api import memory_set_config

        memory_set_config(project_root, "hindsight", {"timeout-seconds": 15})
        assert build_hindsight_backend(project_root) is None
