"""Tests for components/providers/descriptors/loader.py — provider YAML loader.

Validates that the provider loader can build ProviderDescriptor instances
from YAML files and that the loaded descriptors match the current Python
objects field-by-field.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.descriptors.base import (
    ProviderDescriptor,
)
from audiagentic.components.providers.descriptors.loader import (
    PROVIDER_SPEC,
    get_providers_config_dir,
    load_provider_descriptor,
    load_providers_from_directory,
)
from audiagentic.foundation.mcp.json_format import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)


class TestProviderYamlLoader:
    """Test provider YAML loading and field fidelity."""

    def test_load_claude_yaml(self) -> None:
        """Load claude.yaml and verify all fields."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert isinstance(descriptor, ProviderDescriptor)
        assert descriptor.provider_id == "claude"
        assert descriptor.display_name == "Claude (Anthropic)"
        assert descriptor.prompt_aliases == ("cld",)
        assert descriptor.cli_probe == ["claude", "--version"]
        assert descriptor.cli_install is not None
        assert descriptor.cli_install.executable == "claude"
        assert descriptor.mcp_config is not None
        assert descriptor.mcp_config.config_path == ".mcp.json"
        assert descriptor.mcp_config.reader is read_mcp_json
        assert descriptor.mcp_config.writer is write_mcp_json
        assert descriptor.mcp_config.remover is remove_mcp_json

    def test_claude_permissions(self) -> None:
        """Claude permissions match expected values."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert descriptor.permissions.can_write_files is True
        assert descriptor.permissions.can_execute_shell is True
        assert descriptor.permissions.can_browse_web is True
        assert descriptor.permissions.can_read_env is True

    def test_claude_agent_files(self) -> None:
        """Claude agent files are loaded correctly."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert len(descriptor.agent_files) == 3
        assert descriptor.agent_files[0].rel_path == "CLAUDE.md"
        assert descriptor.agent_files[0].managed is True

    def test_claude_host_capabilities(self) -> None:
        """Claude VS Code extension is loaded correctly."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert len(descriptor.host_capabilities) == 1
        assert descriptor.host_capabilities[0].host == "vscode"
        assert descriptor.host_capabilities[0].capability_id == "anthropic.claude-code"

    def test_claude_fetch_catalog_fn(self) -> None:
        """Claude fetch_catalog_fn resolves to callable."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert descriptor.fetch_catalog_fn is not None
        assert callable(descriptor.fetch_catalog_fn)

    def test_load_pi_yaml(self) -> None:
        """Load pi.yaml and verify callable install/uninstall."""
        config_dir = get_providers_config_dir()
        pi_path = config_dir / "pi.yaml"
        if not pi_path.exists():
            pytest.skip("pi.yaml not yet created")

        descriptor = load_provider_descriptor(pi_path)
        assert descriptor.provider_id == "pi"
        assert descriptor.access_mode == "none"
        assert descriptor.cli_install is not None
        assert descriptor.cli_install.package_manager == "pi-harness"
        assert descriptor.on_lsp_enabled is not None
        assert callable(descriptor.on_lsp_enabled)

    def test_pi_callable_steps(self) -> None:
        """Pi install/uninstall steps are callable."""
        config_dir = get_providers_config_dir()
        pi_path = config_dir / "pi.yaml"
        if not pi_path.exists():
            pytest.skip("pi.yaml not yet created")

        descriptor = load_provider_descriptor(pi_path)
        from audiagentic.foundation.workflow.invocation.steps import CallableStep

        assert isinstance(descriptor.cli_install.install, CallableStep)
        assert isinstance(descriptor.cli_install.uninstall, CallableStep)

    def test_provider_spec_required_fields(self) -> None:
        """PROVIDER_SPEC enforces required fields."""
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        with pytest.raises(AudiaGenticError, match="VAL-DESC-003"):
            PROVIDER_SPEC.load({})

    def test_provider_spec_defaults(self) -> None:
        """PROVIDER_SPEC applies defaults for optional fields."""
        data = {"provider_id": "test", "display_name": "Test"}
        resolved = PROVIDER_SPEC.load(data)
        assert resolved["access_mode"] == "cli"
        assert resolved["receive_lsp_mcp"] is True
        assert resolved["cli_probe"] is None
        assert resolved["cli_install"] is None


class TestProvidersConfigDir:
    """Test provider config directory discovery."""

    def test_config_dir_exists(self) -> None:
        """Config directory exists."""
        config_dir = get_providers_config_dir()
        assert config_dir.is_dir()

    def test_config_dir_has_yaml_files(self) -> None:
        """Config directory has at least one YAML file."""
        config_dir = get_providers_config_dir()
        yaml_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))
        assert len(yaml_files) >= 1


class TestLoadProvidersFromDirectory:
    """Test bulk provider loading."""

    def test_load_all_providers(self) -> None:
        """Load all providers from config directory."""
        providers = load_providers_from_directory(get_providers_config_dir())
        assert "claude" in providers
        assert "pi" in providers
        for descriptor in providers.values():
            assert isinstance(descriptor, ProviderDescriptor)
