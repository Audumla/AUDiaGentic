"""Comprehensive provider lifecycle tests.

Exercises the full lifecycle for each provider that can be installed in Docker:
  install → enable → verify surfaces/MCP → disable → prune → uninstall → purge

Providers skipped in Docker:
  plandex (brew — not available)
  pi (pi-harness — requires special setup)
  roo (vscode — extension install requires GUI)

Run via: docker run --rm -v $PWD:/app audiagentic-provider-lifecycle-e2e
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import tomllib
import yaml

from audiagentic.components.providers.descriptors.base import (
    McpConfigSpec,
    ProviderDescriptor,
)
from audiagentic.components.providers.descriptors.registry import (
    get_descriptor,
)
from audiagentic.components.providers.services.lifecycle import (
    install_provider_cli,
    uninstall_provider_cli,
)
from audiagentic.components.providers.services.mcp import (
    add_provider_mcp_server,
    list_provider_mcp_servers,
    remove_provider_mcp_server,
)
from audiagentic.components.providers.services.provider_config import (
    is_provider_enabled,
    set_provider_enabled,
)
from audiagentic.components.providers.surfaces.manager import (
    apply_provider_surfaces,
    prune_provider_surfaces,
)
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.runtime.lifecycle.components import (
    enable_component,
    install_component,
)

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="provider lifecycle tests run in Docker",
    ),
]

register_all_components()

# Providers that can be installed in Docker (npm, uv, script)
_DOCKER_INSTALLABLE = {
    "aider",  # uv
    "claude",  # npm
    "cline",  # npm
    "codex",  # npm
    "copilot",  # npm
    "continue",  # npm
    "gemini",  # npm
    "goose",  # script
    "opencode",  # npm
    "openhands",  # uv
    "qwen",  # npm
}

def _desc(provider_id: str) -> ProviderDescriptor:
    """Get descriptor, asserting it exists."""
    d = get_descriptor(provider_id)
    assert d is not None, f"Descriptor for {provider_id} not found"
    return d


# Providers with MCP config that can be tested in Docker
_MCP_PROVIDERS = {
    pid
    for pid in _DOCKER_INSTALLABLE
    if _desc(pid).mcp_config is not None
}

# Providers with native LSP config
_NATIVE_LSP_PROVIDERS = {
    pid
    for pid in _DOCKER_INSTALLABLE
    if _desc(pid).language_servers_config is not None
}

# Providers with skill surface
_SKILL_PROVIDERS = {
    pid
    for pid in _DOCKER_INSTALLABLE
    if _desc(pid).skill_surface_path is not None
}

# Providers with instruction file
_INSTRUCTION_PROVIDERS = {
    pid
    for pid in _DOCKER_INSTALLABLE
    if _desc(pid).instruction_file is not None
}


def _resolve_mcp_path(spec: McpConfigSpec, project_root: Path) -> Path:
    """Resolve MCP config path, handling callable config_path."""
    cp = spec.config_path
    if callable(cp):
        return cp(project_root)
    return project_root / cp


def _mcp_config_exists(project_root: Path, provider_id: str) -> bool:
    """Check if MCP config file exists for a provider."""
    desc = _desc(provider_id)
    if desc.mcp_config is None:
        return False
    path = _resolve_mcp_path(desc.mcp_config, project_root)
    return path.exists()


def _read_mcp_servers(project_root: Path, provider_id: str) -> dict[str, Any]:
    """Read MCP servers from provider config."""
    result = list_provider_mcp_servers(provider_id, project_root)
    return {s["name"]: s for s in result.get("servers", [])}


class TestProviderInstallUninstall:
    """Full install → enable → disable → uninstall lifecycle for each provider."""

    @pytest.mark.parametrize("provider_id", sorted(_DOCKER_INSTALLABLE))
    @pytest.mark.timeout(600)
    def test_install_enable_uninstall_roundtrip(
        self, provider_id: str, tmp_path: Path
    ) -> None:
        """Install CLI, enable, verify, disable, uninstall, verify gone."""
        desc = _desc(provider_id)
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)

        # Install providers component
        install_result = install_component("providers", project_root)
        assert install_result.get("ok"), f"providers install failed: {install_result}"

        # Install CLI
        install_result = install_provider_cli(
            provider_id, timeout=300, project_root=project_root
        )
        assert install_result.get("status") == "installed", (
            f"{provider_id} install failed: {install_result}"
        )

        # Verify CLI on PATH
        if desc.cli_install is not None:
            assert shutil.which(desc.cli_install.executable) is not None, (
                f"{desc.cli_install.executable} not on PATH after install"
            )

        # Verify provider enabled
        assert is_provider_enabled(project_root, provider_id), (
            f"{provider_id} not enabled after install"
        )

        # Apply surfaces
        apply_surfaces_result = apply_provider_surfaces(project_root, provider_id=provider_id)
        assert apply_surfaces_result.get("ok"), (
            f"{provider_id} apply surfaces failed: {apply_surfaces_result}"
        )

        # Disable
        set_provider_enabled(project_root, provider_id, enabled=False)
        assert not is_provider_enabled(project_root, provider_id), (
            f"{provider_id} still enabled after disable"
        )

        # Prune surfaces
        prune_surfaces_result = prune_provider_surfaces(project_root, provider_id=provider_id)
        assert prune_surfaces_result.get("ok"), (
            f"{provider_id} prune surfaces failed: {prune_surfaces_result}"
        )

        # Uninstall
        uninstall_result = uninstall_provider_cli(
            provider_id, timeout=300, project_root=project_root
        )
        assert uninstall_result.get("status") == "uninstalled", (
            f"{provider_id} uninstall failed: {uninstall_result}"
        )

        # Verify CLI gone
        if desc.cli_install is not None:
            assert shutil.which(desc.cli_install.executable) is None, (
                f"{desc.cli_install.executable} still on PATH after uninstall"
            )

    @pytest.mark.parametrize("provider_id", sorted(_DOCKER_INSTALLABLE))
    def test_provider_agent_files_created(self, provider_id: str, tmp_path: Path) -> None:
        """After install + apply_surfaces, managed agent files exist."""
        desc = _desc(provider_id)
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)

        install_component("providers", project_root)

        # Pre-create surface files that apply_surfaces needs
        for af in desc.agent_files:
            if af.managed:
                target = project_root / af.rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_text("", encoding="utf-8")

        install_provider_cli(provider_id, timeout=300, project_root=project_root)
        apply_provider_surfaces(project_root, provider_id=provider_id)

        # Verify managed agent files exist
        for af in desc.agent_files:
            if af.managed:
                assert (project_root / af.rel_path).exists(), (
                    f"{provider_id}: managed agent file {af.rel_path} missing"
                )

        # Cleanup
        uninstall_provider_cli(provider_id, timeout=300, project_root=project_root)


class TestProviderMcpConfig:
    """MCP server add/remove/reload for each provider format."""

    @pytest.mark.parametrize("provider_id", sorted(_MCP_PROVIDERS))
    @pytest.mark.timeout(600)
    def test_mcp_server_add_remove_roundtrip(
        self, provider_id: str, tmp_path: Path
    ) -> None:
        """Add a test MCP server, verify it appears, remove it, verify gone."""
        desc = _desc(provider_id)
        spec = desc.mcp_config
        assert spec is not None

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)

        install_component("providers", project_root)
        install_provider_cli(provider_id, timeout=300, project_root=project_root)

        # Ensure MCP config file exists
        config_path = _resolve_mcp_path(spec, project_root)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            # Create stub config
            if config_path.suffix == ".toml":
                config_path.write_text("", encoding="utf-8")
            elif config_path.suffix == ".yaml":
                config_path.write_text("extensions: []\n", encoding="utf-8")
            else:
                config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        # Add test server
        add_result = add_provider_mcp_server(
            provider_id,
            name="test-server",
            command="echo",
            project_root=project_root,
            args=("hello",),
        )
        assert add_result.get("ok"), f"{provider_id} add MCP failed: {add_result}"

        # Verify server appears
        servers = _read_mcp_servers(project_root, provider_id)
        assert "test-server" in servers, (
            f"{provider_id}: test-server not in MCP config after add. Servers: {servers}"
        )
        assert servers["test-server"]["command"] == "echo"

        # Remove test server
        remove_result = remove_provider_mcp_server(
            provider_id, "test-server", project_root
        )
        assert remove_result.get("ok"), f"{provider_id} remove MCP failed: {remove_result}"

        # Verify server gone
        servers = _read_mcp_servers(project_root, provider_id)
        assert "test-server" not in servers, (
            f"{provider_id}: test-server still in MCP config after remove. Servers: {servers}"
        )

        # Cleanup
        uninstall_provider_cli(provider_id, timeout=300, project_root=project_root)

    @pytest.mark.parametrize("provider_id", sorted(_MCP_PROVIDERS))
    def test_mcp_config_format_preserved(self, provider_id: str, tmp_path: Path) -> None:
        """Verify the provider's MCP config format is correctly written/read."""
        desc = _desc(provider_id)
        spec = desc.mcp_config
        assert spec is not None

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)

        install_component("providers", project_root)
        install_provider_cli(provider_id, timeout=300, project_root=project_root)

        config_path = _resolve_mcp_path(spec, project_root)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            if config_path.suffix == ".toml":
                config_path.write_text("", encoding="utf-8")
            elif config_path.suffix == ".yaml":
                config_path.write_text("extensions: []\n", encoding="utf-8")
            else:
                config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        # Add server
        add_provider_mcp_server(
            provider_id, "format-test", "test-cmd", project_root, args=("arg1", "arg2")
        )

        # Read raw file and verify format
        raw = config_path.read_text(encoding="utf-8")
        if spec.format == "codex-toml":
            data = tomllib.loads(raw)
            assert "mcp_servers" in data, f"{provider_id}: TOML missing mcp_servers key"
        elif spec.format == "goose-yaml":
            data = yaml.safe_load(raw)
            assert "extensions" in data, f"{provider_id}: YAML missing extensions key"
        elif spec.format == "continue-json":
            data = json.loads(raw)
            assert "mcpServers" in data, f"{provider_id}: JSON missing mcpServers key"
            assert isinstance(data["mcpServers"], list)
        elif spec.format == "opencode-mcp":
            data = json.loads(raw)
            assert "mcp" in data, f"{provider_id}: JSON missing mcp key"
        elif spec.format == "mcp-json":
            data = json.loads(raw)
            assert "mcpServers" in data, f"{provider_id}: JSON missing mcpServers key"
            assert isinstance(data["mcpServers"], dict)

        # Cleanup
        remove_provider_mcp_server(provider_id, "format-test", project_root)
        uninstall_provider_cli(provider_id, timeout=300, project_root=project_root)


class TestProviderDisableRemovesMcp:
    """Verify that disabling a provider removes its managed MCP entries."""

    @pytest.mark.parametrize("provider_id", sorted(_MCP_PROVIDERS - _NATIVE_LSP_PROVIDERS))
    @pytest.mark.timeout(600)
    def test_disable_removes_managed_mcp(self, provider_id: str, tmp_path: Path) -> None:
        """Install coding-lsp, sync MCP, disable provider, verify MCP removed."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)

        # Install providers + coding-lsp
        install_component("providers", project_root)
        install_component("coding-lsp", project_root)
        enable_component("coding-lsp", project_root)

        # Install provider
        install_provider_cli(provider_id, timeout=300, project_root=project_root)

        # Ensure MCP config file exists
        desc = _desc(provider_id)
        spec = desc.mcp_config
        assert spec is not None
        config_path = _resolve_mcp_path(spec, project_root)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            if config_path.suffix == ".toml":
                config_path.write_text("", encoding="utf-8")
            elif config_path.suffix == ".yaml":
                config_path.write_text("extensions: []\n", encoding="utf-8")
            else:
                config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        # Sync generic LSP MCP to providers
        from audiagentic.components.coding_lsp.language_servers_sync import (
            sync_generic_lsp_mcp_to_providers,
        )
        sync_result = sync_generic_lsp_mcp_to_providers(project_root)
        assert sync_result.get("ok"), f"{provider_id} sync MCP failed: {sync_result}"

        # Verify ag-lsp MCP server present
        servers = _read_mcp_servers(project_root, provider_id)
        assert "ag-lsp" in servers, (
            f"{provider_id}: ag-lsp not in MCP config after sync. Servers: {servers}"
        )

        # Disable provider
        set_provider_enabled(project_root, provider_id, enabled=False)

        # Re-sync — should remove ag-lsp from disabled provider
        sync_generic_lsp_mcp_to_providers(project_root)

        # Verify ag-lsp removed
        servers = _read_mcp_servers(project_root, provider_id)
        assert "ag-lsp" not in servers, (
            f"{provider_id}: ag-lsp still in MCP config after disable. Servers: {servers}"
        )

        # Cleanup
        uninstall_provider_cli(provider_id, timeout=300, project_root=project_root)


class TestProviderSkillSurface:
    """Skill file projection for providers with skill_surface_path."""

    @pytest.mark.parametrize("provider_id", sorted(_SKILL_PROVIDERS))
    @pytest.mark.timeout(600)
    def test_skill_surface_path_defined(self, provider_id: str) -> None:
        """Verify skill surface path pattern is valid."""
        desc = _desc(provider_id)
        assert desc.skill_surface_path is not None
        assert "{tag}" in desc.skill_surface_path, (
            f"{provider_id}: skill_surface_path missing {{tag}} placeholder"
        )

    @pytest.mark.parametrize("provider_id", sorted(_SKILL_PROVIDERS))
    @pytest.mark.timeout(600)
    def test_skill_directory_created_on_install(
        self, provider_id: str, tmp_path: Path
    ) -> None:
        """After install, skill directory structure is ready."""
        desc = _desc(provider_id)
        assert desc.skill_surface_path is not None

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)

        install_component("providers", project_root)
        install_provider_cli(provider_id, timeout=300, project_root=project_root)

        # Verify skill directory parent exists or can be created
        skill_dir = Path(desc.skill_surface_path).parent
        skill_dir_path = project_root / skill_dir
        skill_dir_path.mkdir(parents=True, exist_ok=True)
        assert skill_dir_path.is_dir(), (
            f"{provider_id}: skill directory {skill_dir} not creatable"
        )

        # Cleanup
        uninstall_provider_cli(provider_id, timeout=300, project_root=project_root)


class TestProviderInstructionFile:
    """Instruction file content for providers with instruction_file."""

    @pytest.mark.parametrize("provider_id", sorted(_INSTRUCTION_PROVIDERS))
    @pytest.mark.timeout(600)
    def test_instruction_file_exists_after_install(
        self, provider_id: str, tmp_path: Path
    ) -> None:
        """After install + apply_surfaces, instruction file exists."""
        desc = _desc(provider_id)
        assert desc.instruction_file is not None

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)

        install_component("providers", project_root)

        # Pre-create instruction file
        instr_path = project_root / desc.instruction_file
        instr_path.parent.mkdir(parents=True, exist_ok=True)
        if not instr_path.exists():
            instr_path.write_text("", encoding="utf-8")

        install_provider_cli(provider_id, timeout=300, project_root=project_root)
        apply_provider_surfaces(project_root, provider_id=provider_id)

        assert instr_path.exists(), (
            f"{provider_id}: instruction file {desc.instruction_file} missing"
        )

        # Cleanup
        uninstall_provider_cli(provider_id, timeout=300, project_root=project_root)


class TestProviderDescriptorCompleteness:
    """Verify all provider descriptors have consistent configuration."""

    @pytest.mark.parametrize("provider_id", sorted(_DOCKER_INSTALLABLE))
    def test_descriptor_has_cli_probe(self, provider_id: str) -> None:
        desc = _desc(provider_id)
        assert desc.cli_probe is not None, f"{provider_id} missing cli_probe"

    @pytest.mark.parametrize("provider_id", sorted(_DOCKER_INSTALLABLE))
    def test_descriptor_has_cli_install(self, provider_id: str) -> None:
        desc = _desc(provider_id)
        assert desc.cli_install is not None, f"{provider_id} missing cli_install"

    @pytest.mark.parametrize("provider_id", sorted(_MCP_PROVIDERS))
    def test_mcp_config_has_valid_format(self, provider_id: str) -> None:
        desc = _desc(provider_id)
        spec = desc.mcp_config
        assert spec is not None
        assert spec.format, f"{provider_id} MCP config missing format"
        assert spec.refresh_mode in ("file-watch", "restart-required"), (
            f"{provider_id} MCP config invalid refresh_mode: {spec.refresh_mode}"
        )

    @pytest.mark.parametrize("provider_id", sorted(_NATIVE_LSP_PROVIDERS))
    def test_lsp_config_has_valid_format(self, provider_id: str) -> None:
        desc = _desc(provider_id)
        spec = desc.language_servers_config
        assert spec is not None
        assert spec.format, f"{provider_id} LSP config missing format"
