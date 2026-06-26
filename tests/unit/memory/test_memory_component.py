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
        assert "base-url" in schema
        assert "timeout-seconds" in schema
        assert schema["timeout-seconds"].default == 30

    def test_hindsight_has_no_provider_matrix(self, project_root: Path) -> None:
        """Provider matrix is provider-owned knowledge, not memory-owned."""
        impl = get_implementation("memory", "hindsight")
        assert impl is not None
        assert "provider-matrix" not in impl.raw


class TestImplementationSelection:
    """Test implementation selection and state persistence."""

    def test_default_implementation_is_hindsight(self, project_root: Path) -> None:
        """When no implementation is enabled, the default (hindsight) is returned."""
        from audiagentic.components.memory.memory_api import _active_implementation_id

        active = _active_implementation_id(project_root)
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
            "base-url": "https://hindsight.example.com",
        })
        assert result["implementation"] == "hindsight"
        assert result["config"]["base-url"] == "https://hindsight.example.com"
        assert "base-url" in result["updated_keys"]


class TestMemoryStatus:
    """Test memory_status output contract — memory-owned facts only."""

    def test_status_with_no_config(self, project_root: Path) -> None:
        """Status returns configured=False when no options are set."""
        from audiagentic.components.memory.memory_api import memory_status

        result = memory_status(project_root)
        assert result["active_implementation"] == "hindsight"
        assert result["configured"] is False
        # No provider-specific fields
        assert "provider_support" not in result
        assert "unsupported_providers" not in result

    def test_status_with_config(self, project_root: Path) -> None:
        """Status returns configured=True when options are set."""
        from audiagentic.components.memory.memory_api import (
            memory_set_config,
            memory_status,
        )

        memory_set_config(project_root, "hindsight", {
            "base-url": "https://hindsight.example.com",
        })
        result = memory_status(project_root)
        assert result["configured"] is True


class TestDynamicContributions:
    """Test that memory exports provider-agnostic contributions."""

    def test_no_config_returns_empty(self, project_root: Path) -> None:
        """Unconfigured memory contributes nothing."""
        from audiagentic.components.memory.memory_api import build_memory_contributions

        contribs = build_memory_contributions(project_root=project_root)
        assert contribs == []

    def test_configured_memory_contributes(self, project_root: Path) -> None:
        """Configured memory exports contribution with backend info."""
        from audiagentic.components.memory.memory_api import (
            build_memory_contributions,
            memory_set_config,
        )

        memory_set_config(project_root, "hindsight", {
            "base-url": "https://hindsight.example.com",
        })
        contribs = build_memory_contributions(project_root=project_root)
        assert len(contribs) == 1
        contrib = contribs[0]
        assert contrib["contribution_id"] == "memory/hindsight"
        assert contrib["owner_component"] == "memory"
        assert "Hindsight" in contrib["title"]
        assert "hindsight.example.com" in contrib["body"]

    def test_contribution_has_no_provider_ids(self, project_root: Path) -> None:
        """Memory contribution does not encode provider IDs."""
        from audiagentic.components.memory.memory_api import (
            build_memory_contributions,
            memory_set_config,
        )

        memory_set_config(project_root, "hindsight", {
            "base-url": "https://hindsight.example.com",
        })
        contribs = build_memory_contributions(project_root=project_root)
        body = contribs[0]["body"]
        # Should not contain provider IDs or file paths
        assert "claude" not in body.lower()
        assert "opencode" not in body.lower()
        assert "AGENTS.md" not in body
        assert "CLAUDE.md" not in body

    def test_no_base_url_returns_empty(self, project_root: Path) -> None:
        """Config without base-url contributes nothing (not actionable)."""
        from audiagentic.components.memory.memory_api import (
            build_memory_contributions,
            memory_set_config,
        )

        memory_set_config(project_root, "hindsight", {
            "timeout-seconds": 60,
        })
        contribs = build_memory_contributions(project_root=project_root)
        assert contribs == []


class TestIdempotentApply:
    """Test that repeated config apply is idempotent."""

    def test_repeated_set_config_is_idempotent(self, project_root: Path) -> None:
        """Setting the same config twice yields no extra drift."""
        from audiagentic.components.memory.memory_api import memory_set_config

        updates = {"base-url": "https://hindsight.example.com"}
        result1 = memory_set_config(project_root, "hindsight", updates)
        result2 = memory_set_config(project_root, "hindsight", updates)

        assert result1["config"] == result2["config"]
