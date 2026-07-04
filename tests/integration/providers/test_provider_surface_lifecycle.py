"""Integration tests: provider surface lifecycle.

Verifies that after each component lifecycle operation (install, uninstall,
enable, disable) the provider MCP config files and provider surface files
(CLAUDE.md etc.) reflect the correct state.

Skipped unless AUDIAGENTIC_DOCKER_TESTS=1 (enforced by conftest.py).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
import tomllib
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
    reason="provider surface lifecycle tests require Docker isolation",
)
from tests.integration.lifecycle.harness import (
    component_sandbox,
    disable_component,
    enable_component,
    install_with_deps,
    uninstall_component,
)

from audiagentic.foundation.components.registry import all_descriptors

# --------------------------------------------------------------------------- #
# Component registration
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Provider surface files that need to exist before apply_surfaces will write
# --------------------------------------------------------------------------- #

_SURFACE_FILES: list[str] = [
    "CLAUDE.md",
    "AGENTS.md",
    ".clinerules/audiagentic.md",
    ".roo/rules/audiagentic.md",
]

# Provider MCP config paths relative to project root, keyed by format label.
_MCP_CONFIG_PATHS: dict[str, str] = {
    "mcp-json-claude":    ".mcp.json",
    "codex-toml":         ".codex/config.toml",
    "opencode-mcp":       ".opencode/opencode.json",
    "mcp-json-gemini":    ".gemini/settings.json",
    "goose-yaml":         ".goose/config.yaml",
    "continue-json":      ".continue/config.json",
}

# Components under test for parametrized tests
_PROPAGATION_COMPONENTS = ["agent-ledger", "agent-planning", "coding-lsp", "source-control"]
_SURFACE_COMPONENTS = ["agent-ledger", "agent-planning", "source-control", "coding-lsp"]


# --------------------------------------------------------------------------- #
# ProviderSurfaceHarness helpers
# --------------------------------------------------------------------------- #

def setup_provider_surfaces(project_root: Path) -> None:
    """Create surface files so apply_provider_surfaces has files to write into."""
    for rel in _SURFACE_FILES:
        target = project_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("", encoding="utf-8")

    # Create stub MCP config files so the writer functions have something to update.
    (project_root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {}}), encoding="utf-8"
    )
    _ensure_dir_and_stub(project_root / ".codex" / "config.toml", "")
    _ensure_dir_and_stub(project_root / ".opencode" / "opencode.json", '{"mcp": {}}')
    _ensure_dir_and_stub(project_root / ".gemini" / "settings.json", '{"mcpServers": {}}')
    _ensure_dir_and_stub(
        project_root / ".goose" / "config.yaml",
        yaml.dump({"extensions": []}, default_flow_style=False),
    )
    _ensure_dir_and_stub(
        project_root / ".continue" / "config.json",
        json.dumps({"mcpServers": []}),
    )

    # Enabled-aware projection: a provider only receives managed MCP entries and
    # surface files when it is enabled. Enable every provider so propagation and
    # surface apply target the stub configs / surface files created above.
    from audiagentic.components.providers.descriptors.registry import (
        all_descriptors as all_provider_descriptors,
    )
    from audiagentic.components.providers.services.provider_config import (
        set_provider_enabled,
    )
    for provider_id in all_provider_descriptors():
        set_provider_enabled(project_root, provider_id, enabled=True)


def _ensure_dir_and_stub(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def apply_surfaces(project_root: Path) -> None:
    """Synchronise all provider MCP configs and surface files to current state.

    Surface changes may not fire in test isolation (no event bus), so we call
    these explicitly.
    """
    from audiagentic.components.providers.surfaces.manager import (
        apply_provider_surfaces,
        prune_provider_surfaces,
    )
    from audiagentic.foundation.lifecycle.component_mcp import sync_all_provider_mcp_servers

    sync_all_provider_mcp_servers(project_root)
    prune_provider_surfaces(project_root)
    apply_provider_surfaces(project_root)


def mcp_servers_in(project_root: Path, config_path: str) -> set[str]:
    """Read an MCP config file and return the set of server names present."""
    path = project_root / config_path

    if not path.exists():
        return set()

    suffix = path.suffix.lower()
    name = path.name.lower()

    if suffix == ".toml":
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return set()
        return set((data.get("mcp_servers") or {}).keys())

    # YAML-based config (goose)
    if suffix in (".yaml", ".yml"):
        try:
            data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return set()
        # Goose: extensions list of dicts with "name" key
        return {
            ext.get("name", "")
            for ext in data.get("extensions", [])
            if isinstance(ext, dict) and ext.get("name")
        }

    # JSON-based configs
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    # OpenCode: {"mcp": {"name": ...}}
    if "opencode.json" in name:
        return set(data.get("mcp", {}).keys())

    # Continue: {"mcpServers": [{"name": ...}]}
    if isinstance(data.get("mcpServers"), list):
        return {s.get("name", "") for s in data["mcpServers"] if isinstance(s, dict) and s.get("name")}

    # Standard mcp-json: {"mcpServers": {"name": ...}}
    if isinstance(data.get("mcpServers"), dict):
        return set(data["mcpServers"].keys())

    return set()


def managed_blocks_in(file_path: Path) -> set[str]:
    """Return contribution IDs present in a file's managed region.

    Blocks are no longer fenced per-id; the managed region holds friendly
    `## Title` headings. Map those titles back to contribution IDs via the
    registry so existing id-based assertions keep working.
    """
    if not file_path.exists():
        return set()
    text = file_path.read_text(encoding="utf-8")
    match = re.search(r"<!-- ag:managed:begin -->(.*?)<!-- ag:managed:end -->", text, re.DOTALL)
    if not match:
        return set()
    titles = re.findall(r"^#{1,6}\s+(.+?)\s*$", match.group(1), re.MULTILINE)
    from audiagentic.components.providers.surfaces.contributions import (
        load_surface_contributions,
    )
    id_by_title = {c.title.strip(): c.contribution_id for c in load_surface_contributions()}
    return {id_by_title[t.strip()] for t in titles if t.strip() in id_by_title}


def _provider_mcp_server_names(component_id: str) -> set[str]:
    """Compute the expected provider-propagated MCP server names dynamically."""
    desc = all_descriptors().get(component_id)
    if desc is None:
        return set()
    names: set[str] = set()
    for ms in (desc.mcp_servers or []):
        if "providers" in ms.propagate:
            names.add(ms.name)
    for ms in (desc.external_mcp_servers or []):
        if "providers" in ms.propagate:
            names.add(ms.name)
    return names


def _component_contribution_block_ids(component_id: str) -> set[str]:
    """Compute expected surface block IDs for a component (project_root=None scan)."""
    from audiagentic.components.providers.surfaces.contributions import (
        load_surface_contributions,
    )

    all_contribs = load_surface_contributions(project_root=None)
    return {c.contribution_id for c in all_contribs if c.owner_component == component_id}


def _provider_mcp_config_paths(project_root: Path) -> list[str]:
    """Return relative paths for provider MCP configs that actually exist."""
    paths = []
    for config_rel in _MCP_CONFIG_PATHS.values():
        if (project_root / config_rel).exists():
            paths.append(config_rel)
    return paths


# --------------------------------------------------------------------------- #
# MCP server propagation tests
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("component_id", _PROPAGATION_COMPONENTS)
def test_install_propagates_mcp_servers_to_providers(
    component_id: str, tmp_path: Path
) -> None:
    """After install, all provider-propagated MCP servers appear in every provider config."""
    expected_servers = _provider_mcp_server_names(component_id)
    if not expected_servers:
        pytest.skip(f"{component_id} has no provider-propagated MCP servers")

    with component_sandbox(tmp_path, f"mcp-install-{component_id}") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps(component_id, sb.repo)
        apply_surfaces(sb.repo)

        for config_rel in _provider_mcp_config_paths(sb.repo):
            present = mcp_servers_in(sb.repo, config_rel)
            missing = expected_servers - present
            assert not missing, (
                f"{component_id}: servers {missing} not found in {config_rel} after install. "
                f"Present: {present}"
            )


@pytest.mark.parametrize("component_id", _PROPAGATION_COMPONENTS)
def test_uninstall_removes_mcp_servers_from_providers(
    component_id: str, tmp_path: Path
) -> None:
    """After uninstall, the component's MCP servers are removed from all provider configs."""
    expected_servers = _provider_mcp_server_names(component_id)
    if not expected_servers:
        pytest.skip(f"{component_id} has no provider-propagated MCP servers")

    with component_sandbox(tmp_path, f"mcp-uninstall-{component_id}") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps(component_id, sb.repo)
        apply_surfaces(sb.repo)

        # Verify they were installed first
        for config_rel in _provider_mcp_config_paths(sb.repo):
            present = mcp_servers_in(sb.repo, config_rel)
            assert expected_servers & present, (
                f"{component_id}: no expected servers in {config_rel} before uninstall"
            )

        uninstall_component(component_id, sb.repo)
        apply_surfaces(sb.repo)

        for config_rel in _provider_mcp_config_paths(sb.repo):
            still_present = mcp_servers_in(sb.repo, config_rel) & expected_servers
            assert not still_present, (
                f"{component_id}: servers {still_present} still in {config_rel} after uninstall"
            )


@pytest.mark.parametrize("component_id", _PROPAGATION_COMPONENTS)
def test_disable_does_not_remove_provider_mcp_servers(
    component_id: str, tmp_path: Path
) -> None:
    """Disable must not remove MCP server entries from provider configs.

    MCP server removal only happens on uninstall.  A disabled component's
    servers should still be present so that the provider can load them if the
    user re-enables without a full reinstall.
    """
    expected_servers = _provider_mcp_server_names(component_id)
    if not expected_servers:
        pytest.skip(f"{component_id} has no provider-propagated MCP servers")

    with component_sandbox(tmp_path, f"mcp-disable-{component_id}") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps(component_id, sb.repo)
        apply_surfaces(sb.repo)

        disable_component(component_id, sb.repo)
        # Do NOT call apply_surfaces — disable should not trigger MCP removal

        for config_rel in _provider_mcp_config_paths(sb.repo):
            present = mcp_servers_in(sb.repo, config_rel)
            missing = expected_servers - present
            assert not missing, (
                f"{component_id}: servers {missing} removed from {config_rel} after disable "
                f"(should remain). Present: {present}"
            )


# --------------------------------------------------------------------------- #
# Surface contribution tests
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("component_id", _SURFACE_COMPONENTS)
def test_install_injects_contribution_blocks(
    component_id: str, tmp_path: Path
) -> None:
    """After install, CLAUDE.md contains managed blocks owned by component_id."""
    expected_blocks = _component_contribution_block_ids(component_id)
    if not expected_blocks:
        pytest.skip(f"{component_id} has no surface contribution blocks")

    with component_sandbox(tmp_path, f"surface-install-{component_id}") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps(component_id, sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"
        present = managed_blocks_in(claude_md)
        missing = expected_blocks - present
        assert not missing, (
            f"{component_id}: blocks {missing} not found in CLAUDE.md after install. "
            f"Present: {present}"
        )


@pytest.mark.parametrize("component_id", _SURFACE_COMPONENTS)
def test_uninstall_removes_contribution_blocks(
    component_id: str, tmp_path: Path
) -> None:
    """After uninstall, the component's managed blocks are gone from CLAUDE.md."""
    expected_blocks = _component_contribution_block_ids(component_id)
    if not expected_blocks:
        pytest.skip(f"{component_id} has no surface contribution blocks")

    with component_sandbox(tmp_path, f"surface-uninstall-{component_id}") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps(component_id, sb.repo)
        apply_surfaces(sb.repo)

        # Sanity: blocks should be present before uninstall
        claude_md = sb.repo / "CLAUDE.md"
        before = managed_blocks_in(claude_md)
        assert expected_blocks & before, (
            f"{component_id}: no expected blocks in CLAUDE.md before uninstall"
        )

        uninstall_component(component_id, sb.repo)
        apply_surfaces(sb.repo)

        after = managed_blocks_in(claude_md)
        still_present = expected_blocks & after
        assert not still_present, (
            f"{component_id}: blocks {still_present} still in CLAUDE.md after uninstall"
        )


@pytest.mark.parametrize("component_id", _SURFACE_COMPONENTS)
def test_disable_removes_contribution_blocks(
    component_id: str, tmp_path: Path
) -> None:
    """After disable + apply_surfaces, the component's managed blocks are pruned."""
    expected_blocks = _component_contribution_block_ids(component_id)
    if not expected_blocks:
        pytest.skip(f"{component_id} has no surface contribution blocks")

    with component_sandbox(tmp_path, f"surface-disable-{component_id}") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps(component_id, sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"
        before = managed_blocks_in(claude_md)
        assert expected_blocks & before, (
            f"{component_id}: no expected blocks before disable"
        )

        disable_component(component_id, sb.repo)
        apply_surfaces(sb.repo)

        after = managed_blocks_in(claude_md)
        still_present = expected_blocks & after
        assert not still_present, (
            f"{component_id}: blocks {still_present} still in CLAUDE.md after disable+apply"
        )


@pytest.mark.parametrize("component_id", _SURFACE_COMPONENTS)
def test_enable_reinjection_after_disable(
    component_id: str, tmp_path: Path
) -> None:
    """Blocks removed on disable reappear after enable + apply_surfaces."""
    expected_blocks = _component_contribution_block_ids(component_id)
    if not expected_blocks:
        pytest.skip(f"{component_id} has no surface contribution blocks")

    with component_sandbox(tmp_path, f"surface-reenable-{component_id}") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps(component_id, sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"

        # Phase 1: disable → blocks gone
        disable_component(component_id, sb.repo)
        apply_surfaces(sb.repo)
        after_disable = managed_blocks_in(claude_md)
        still_present = expected_blocks & after_disable
        assert not still_present, (
            f"{component_id}: blocks {still_present} not pruned after disable"
        )

        # Phase 2: re-enable → blocks back
        enable_component(component_id, sb.repo)
        apply_surfaces(sb.repo)
        after_enable = managed_blocks_in(claude_md)
        missing = expected_blocks - after_enable
        assert not missing, (
            f"{component_id}: blocks {missing} not reinjected after re-enable. "
            f"Present: {after_enable}"
        )


# --------------------------------------------------------------------------- #
# agent-jobs specific tests
# --------------------------------------------------------------------------- #

_AGENT_JOBS_TAG_BLOCKS = {
    "ag-implement/doctrine",
    "ag-plan/doctrine",
    "ag-review/doctrine",
}


def test_agent_jobs_tag_contributions_absent_when_disabled(
    tmp_path: Path,
) -> None:
    """Tag doctrine blocks must not appear in CLAUDE.md when agent-jobs is disabled."""
    with component_sandbox(tmp_path, "aj-disabled") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-jobs", sb.repo)

        disable_component("agent-jobs", sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"
        present = managed_blocks_in(claude_md)
        unexpected = _AGENT_JOBS_TAG_BLOCKS & present
        assert not unexpected, (
            f"Tag doctrine blocks {unexpected} present in CLAUDE.md even though "
            "agent-jobs is disabled"
        )


def test_agent_jobs_tag_contributions_present_when_enabled(
    tmp_path: Path,
) -> None:
    """Tag doctrine blocks appear in CLAUDE.md when agent-jobs is installed (enabled)."""
    with component_sandbox(tmp_path, "aj-enabled") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-jobs", sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"
        present = managed_blocks_in(claude_md)
        missing = _AGENT_JOBS_TAG_BLOCKS - present
        assert not missing, (
            f"Tag doctrine blocks {missing} missing from CLAUDE.md when agent-jobs is enabled. "
            f"Present: {present}"
        )


def test_agent_jobs_tag_contributions_reappear_after_reenable(
    tmp_path: Path,
) -> None:
    """Tag doctrine blocks removed on disable are reinjected after re-enable."""
    with component_sandbox(tmp_path, "aj-reenable") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-jobs", sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"

        # Sanity: blocks present after install
        before = managed_blocks_in(claude_md)
        assert _AGENT_JOBS_TAG_BLOCKS.issubset(before), (
            f"Expected tag blocks not present before disable: {_AGENT_JOBS_TAG_BLOCKS - before}"
        )

        # Disable → blocks gone
        disable_component("agent-jobs", sb.repo)
        apply_surfaces(sb.repo)
        after_disable = managed_blocks_in(claude_md)
        assert not (_AGENT_JOBS_TAG_BLOCKS & after_disable), (
            f"Tag blocks still present after disable: {_AGENT_JOBS_TAG_BLOCKS & after_disable}"
        )

        # Re-enable → blocks back
        enable_component("agent-jobs", sb.repo)
        apply_surfaces(sb.repo)
        after_enable = managed_blocks_in(claude_md)
        missing = _AGENT_JOBS_TAG_BLOCKS - after_enable
        assert not missing, (
            f"Tag doctrine blocks {missing} not reinjected after re-enable. "
            f"Present: {after_enable}"
        )
