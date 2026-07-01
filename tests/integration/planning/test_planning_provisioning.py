"""Integration tests: planning component provisioning lifecycle.

Verifies that after each lifecycle operation (install, disable, enable, uninstall)
the provider MCP configs and surface files (CLAUDE.md etc.) reflect correct state.

All tests use tmp_path sandboxes — no Docker required.  The companion e2e tests
(test_planning_mcp_servers.py) verify the MCP servers respond correctly.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from tests.integration.lifecycle.harness import (
    component_sandbox,
    disable_component,
    enable_component,
    install_with_deps,
    uninstall_component,
)

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import all_descriptors

register_all_components()

# ---------------------------------------------------------------------------
# Helpers (mirrors test_provider_surface_lifecycle.py)
# ---------------------------------------------------------------------------

_SURFACE_FILES = ["CLAUDE.md", "AGENTS.md"]

_MCP_CONFIG_PATHS: dict[str, str] = {
    "mcp-json-claude": ".mcp.json",
    "opencode-mcp":    ".opencode/opencode.json",
    "mcp-json-gemini": ".gemini/settings.json",
    "goose-yaml":      ".goose/config.yaml",
    "continue-json":   ".continue/config.json",
}

# Expected MCP server names from agent-planning component descriptor.
_MGMT_SERVER = "ag-planning-mgmt"
_PLANNING_SERVER = "ag-planning"
_PLANNING_CONTRIBUTION = "agent-planning/process"


def setup_provider_surfaces(project_root: Path) -> None:
    for rel in _SURFACE_FILES:
        target = project_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("", encoding="utf-8")

    (project_root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {}}), encoding="utf-8"
    )
    _stub(project_root / ".opencode" / "opencode.json", '{"mcp": {}}')
    _stub(project_root / ".gemini" / "settings.json", '{"mcpServers": {}}')
    _stub(
        project_root / ".goose" / "config.yaml",
        yaml.dump({"extensions": []}, default_flow_style=False),
    )
    _stub(project_root / ".continue" / "config.json", json.dumps({"mcpServers": []}))

    from audiagentic.components.providers.descriptors.registry import (
        all_descriptors as all_provider_descriptors,
    )
    from audiagentic.components.providers.services.provider_config import (
        set_provider_enabled,
    )
    for provider_id in all_provider_descriptors():
        set_provider_enabled(project_root, provider_id, enabled=True)


def _stub(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def apply_surfaces(project_root: Path) -> None:
    from audiagentic.components.providers.surfaces.manager import (
        apply_provider_surfaces,
        prune_provider_surfaces,
    )
    from audiagentic.runtime.lifecycle.component_mcp import sync_all_provider_mcp_servers

    sync_all_provider_mcp_servers(project_root)
    prune_provider_surfaces(project_root)
    apply_provider_surfaces(project_root)


def mcp_servers_in(project_root: Path, config_path: str) -> set[str]:
    import tomllib
    path = project_root / config_path
    if not path.exists():
        return set()
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix == ".toml":
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        return set((data.get("mcp_servers") or {}).keys())
    if suffix in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return set()
        return {
            ext.get("name", "")
            for ext in data.get("extensions", [])
            if isinstance(ext, dict) and ext.get("name")
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if "opencode.json" in name:
        return set(data.get("mcp", {}).keys())
    if isinstance(data.get("mcpServers"), list):
        return {s.get("name", "") for s in data["mcpServers"] if isinstance(s, dict)}
    if isinstance(data.get("mcpServers"), dict):
        return set(data["mcpServers"].keys())
    return set()


def managed_blocks_in(file_path: Path) -> set[str]:
    if not file_path.exists():
        return set()
    text = file_path.read_text(encoding="utf-8")
    match = re.search(r"<!-- ag:managed:begin -->(.*?)<!-- ag:managed:end -->", text, re.DOTALL)
    if not match:
        return set()
    titles = re.findall(r"^#{1,6}\s+(.+?)\s*$", match.group(1), re.MULTILINE)
    from audiagentic.components.providers.surfaces.contributions import load_surface_contributions
    id_by_title = {c.title.strip(): c.contribution_id for c in load_surface_contributions()}
    return {id_by_title[t.strip()] for t in titles if t.strip() in id_by_title}


def mcp_config_paths(project_root: Path) -> list[str]:
    return [rel for rel in _MCP_CONFIG_PATHS.values() if (project_root / rel).exists()]


# ---------------------------------------------------------------------------
# Component descriptor sanity
# ---------------------------------------------------------------------------

def test_component_declares_mgmt_and_planning_mcp_servers() -> None:
    desc = all_descriptors().get("agent-planning")
    assert desc is not None, "agent-planning not in components registry"
    names = {ms.name for ms in (desc.mcp_servers or [])}
    assert _MGMT_SERVER in names, f"{_MGMT_SERVER} missing from component mcp-servers"
    assert _PLANNING_SERVER in names, f"{_PLANNING_SERVER} missing from component mcp-servers"


def test_mgmt_mcp_propagates_to_audiagentic_only() -> None:
    desc = all_descriptors()["agent-planning"]
    mgmt = next(ms for ms in desc.mcp_servers if ms.name == _MGMT_SERVER)
    assert "audiagentic" in mgmt.propagate
    assert "providers" not in mgmt.propagate


def test_planning_mcp_propagates_to_providers_only() -> None:
    """ag-planning is an operational server — providers only, never the harness."""
    desc = all_descriptors()["agent-planning"]
    planning = next(ms for ms in desc.mcp_servers if ms.name == _PLANNING_SERVER)
    assert "providers" in planning.propagate
    assert "audiagentic" not in planning.propagate


# ---------------------------------------------------------------------------
# Provider MCP propagation — install / uninstall / disable
# ---------------------------------------------------------------------------

def test_install_propagates_ag_planning_to_all_provider_configs(tmp_path: Path) -> None:
    with component_sandbox(tmp_path, "plan-mcp-install") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        for config_rel in mcp_config_paths(sb.repo):
            present = mcp_servers_in(sb.repo, config_rel)
            assert _PLANNING_SERVER in present, (
                f"{_PLANNING_SERVER} missing from {config_rel} after install. Present: {present}"
            )


def test_install_does_not_propagate_mgmt_mcp_to_provider_configs(tmp_path: Path) -> None:
    with component_sandbox(tmp_path, "plan-mgmt-not-in-providers") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        for config_rel in mcp_config_paths(sb.repo):
            present = mcp_servers_in(sb.repo, config_rel)
            assert _MGMT_SERVER not in present, (
                f"{_MGMT_SERVER} should not be in provider config {config_rel}. "
                f"It propagates only to audiagentic. Present: {present}"
            )


def test_uninstall_removes_ag_planning_from_provider_configs(tmp_path: Path) -> None:
    with component_sandbox(tmp_path, "plan-mcp-uninstall") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        for config_rel in mcp_config_paths(sb.repo):
            assert _PLANNING_SERVER in mcp_servers_in(sb.repo, config_rel), (
                f"sanity: {_PLANNING_SERVER} not in {config_rel} before uninstall"
            )

        uninstall_component("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        for config_rel in mcp_config_paths(sb.repo):
            present = mcp_servers_in(sb.repo, config_rel)
            assert _PLANNING_SERVER not in present, (
                f"{_PLANNING_SERVER} still in {config_rel} after uninstall. Present: {present}"
            )


def test_disable_preserves_ag_planning_in_provider_configs(tmp_path: Path) -> None:
    """Disable must not remove MCP entries from provider configs (only uninstall does)."""
    with component_sandbox(tmp_path, "plan-mcp-disable") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        disable_component("agent-planning", sb.repo)

        for config_rel in mcp_config_paths(sb.repo):
            present = mcp_servers_in(sb.repo, config_rel)
            assert _PLANNING_SERVER in present, (
                f"{_PLANNING_SERVER} removed from {config_rel} after disable "
                f"(should stay until uninstall). Present: {present}"
            )


# ---------------------------------------------------------------------------
# Surface contributions — CLAUDE.md injection
# ---------------------------------------------------------------------------

def test_install_injects_planning_process_contribution(tmp_path: Path) -> None:
    with component_sandbox(tmp_path, "plan-surface-install") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        present = managed_blocks_in(sb.repo / "CLAUDE.md")
        assert _PLANNING_CONTRIBUTION in present, (
            f"{_PLANNING_CONTRIBUTION} not in CLAUDE.md after install. Present: {present}"
        )


def test_disable_removes_planning_contribution_from_surfaces(tmp_path: Path) -> None:
    with component_sandbox(tmp_path, "plan-surface-disable") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"
        assert _PLANNING_CONTRIBUTION in managed_blocks_in(claude_md), "sanity: block not present before disable"

        disable_component("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        present = managed_blocks_in(claude_md)
        assert _PLANNING_CONTRIBUTION not in present, (
            f"{_PLANNING_CONTRIBUTION} still in CLAUDE.md after disable+apply. Present: {present}"
        )


def test_enable_reinjection_restores_planning_contribution(tmp_path: Path) -> None:
    with component_sandbox(tmp_path, "plan-surface-reenable") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"

        disable_component("agent-planning", sb.repo)
        apply_surfaces(sb.repo)
        assert _PLANNING_CONTRIBUTION not in managed_blocks_in(claude_md), "sanity: block should be gone after disable"

        enable_component("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        present = managed_blocks_in(claude_md)
        assert _PLANNING_CONTRIBUTION in present, (
            f"{_PLANNING_CONTRIBUTION} not reinjected after re-enable. Present: {present}"
        )


def test_uninstall_removes_planning_contribution_from_surfaces(tmp_path: Path) -> None:
    with component_sandbox(tmp_path, "plan-surface-uninstall") as sb:
        install_with_deps("project", sb.repo)
        install_with_deps("providers", sb.repo)
        setup_provider_surfaces(sb.repo)
        install_with_deps("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        claude_md = sb.repo / "CLAUDE.md"
        assert _PLANNING_CONTRIBUTION in managed_blocks_in(claude_md), "sanity"

        uninstall_component("agent-planning", sb.repo)
        apply_surfaces(sb.repo)

        present = managed_blocks_in(claude_md)
        assert _PLANNING_CONTRIBUTION not in present, (
            f"{_PLANNING_CONTRIBUTION} still in CLAUDE.md after uninstall. Present: {present}"
        )


# ---------------------------------------------------------------------------
# Sync payload
# ---------------------------------------------------------------------------

def test_install_sync_action_is_reload_required(tmp_path: Path) -> None:
    """agent-planning has MCP servers — install must signal reload_required."""
    from audiagentic.runtime.lifecycle.components import install_component

    with component_sandbox(tmp_path, "plan-sync") as sb:
        install_with_deps("project", sb.repo)
        result = install_component("agent-planning", sb.repo)
        sync = result.get("sync", {})
        assert sync.get("action") == "reload_required", (
            f"Expected reload_required, got {sync.get('action')!r}"
        )
