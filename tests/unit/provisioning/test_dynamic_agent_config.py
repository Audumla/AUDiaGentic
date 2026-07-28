from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audiagentic import launcher
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.prompt_injections import (
    build_system_prompt_injections as build_system_md_injections,
)
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.lifecycle.components import install_component
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.json_format import _resolve_command
from audiagentic.foundation.mcp.projection import collect_component_mcp_entries


def _collect(project_root: Path) -> dict[str, McpServerEntry]:
    """Same harness-agnostic source both the launch-time
    MCP surface build from -- entries carry unresolved python placeholders until
    a consumer resolves them (see _resolve_command)."""
    return collect_component_mcp_entries(
        project_root, propagation_target="providers", require_enabled=True
    )


def test_build_system_md_injections_uses_explicit_project_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    other_root = tmp_path / "other"
    project_root.mkdir()
    other_root.mkdir()

    register_all_components()
    install_component("project", project_root)
    install_component("coding-lsp", project_root)
    monkeypatch.chdir(other_root)

    injections = build_system_md_injections(project_root)

    # No consolidated tool catalog is injected; per-tool defs are MCP-advertised.
    assert "MCP tools" not in injections
    assert "Available components" in injections
    assert "installed/enabled" in injections["Available components"]
    assert "`providers`" in injections["Available components"]
    assert "not installed" in injections["Available components"]


def test_collect_mcp_entries_rebuilds_from_installed_components(
    tmp_path: Path,
) -> None:
    """The harness-agnostic entry source contains enabled functional servers, not bootstrap management."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    register_all_components()

    initial = _collect(project_root)
    assert "ag-lsp-mgmt" not in initial

    install_component("coding-lsp", project_root)
    updated = _collect(project_root)

    assert "ag-lsp" in updated
    assert "ag-lsp-mgmt" not in updated


def test_agents_functional_servers_are_in_collected_mcp_entries(
    tmp_path: Path,
) -> None:
    """Provider-facing agent resolution and gateway servers are collected."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    register_all_components()
    install_component("agents", project_root)
    entries = _collect(project_root)

    assert {"ag-agents", "ag-agents-gateway"} <= set(entries)
    assert "ag-agents-mgmt" not in entries


def test_management_only_provider_server_is_not_in_collected_mcp_entries(
    tmp_path: Path,
) -> None:
    """Bootstrap management servers are not projected into the functional entry set."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    register_all_components()
    install_component("providers", project_root)
    entries = _collect(project_root)

    assert "ag-providers-mgmt" not in entries


def test_ledger_component_uses_optional_server_module_in_collected_mcp_entries(
    tmp_path: Path,
) -> None:
    """The functional ledger server appears; its bootstrap management peer does not."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    register_all_components()
    install_component("agent-ledger", project_root)
    entries = _collect(project_root)

    assert "ag-ledger" in entries
    assert "ag-ledger-mgmt" not in entries


def test_collected_mcp_entry_command_resolves_to_runtime_python(
    tmp_path: Path,
) -> None:
    """Consumers (launch-time MCP surface) resolve the
    portability placeholder via _resolve_command before spawning -- entries
    themselves still carry it unresolved."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    register_all_components()
    install_component("agent-ledger", project_root)
    entries = _collect(project_root)

    resolved = _resolve_command(entries["ag-ledger"].command)
    assert resolved == str(sys.executable)
    assert resolved != "__AUDIAGENTIC_PYTHON__"


def test_component_mcp_metadata_loads_from_yaml() -> None:
    register_all_components()

    project_decl = get_mcp_server_declaration("project", "ag-project-mgmt")
    session_decl = get_mcp_server_declaration("session", "ag-session-mgmt")
    ledger_decl = get_mcp_server_declaration("agent-ledger", "ag-ledger")

    assert project_decl is not None
    assert "list_components" in project_decl.instructions
    assert "project_status" in project_decl.tool_descriptions

    assert session_decl is not None
    assert "status" in session_decl.tool_descriptions

    assert ledger_decl is not None
    assert ledger_decl.module == "audiagentic.components.ledger.ledger_mcp"


def test_component_install_refreshes_materialized_agent_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Component install refreshes materialized config; no reload marker
    is written (HA05 — request_runtime_reload deleted)."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()

    refresh_calls: list[tuple[Path, str]] = []

    monkeypatch.setattr(
        "audiagentic.foundation.paths.home.global_harness_runtime",
        lambda: harness_root,
    )
    # Satisfy the refresh gate: a supported harness is installed on the system.
    monkeypatch.setattr(
        "audiagentic.runtime.harness.resolution.harness_cli_available",
        lambda _harness_type: "/usr/bin/pi",
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.materialize_provider_config",
        lambda project_root, provider_id, **_kw: refresh_calls.append((project_root, provider_id)),
    )
    monkeypatch.setattr(
        "audiagentic.components.project.project_components.attach_harness_refresh",
        lambda result, _project_root: result,
    )

    args = argparse.Namespace(component_cmd="install", component_id="coding-lsp")

    rc = launcher._cmd_component(args, project_root)

    assert rc == 0
    assert refresh_calls
    assert all(call[0] == project_root and call[1] == "pi" for call in refresh_calls)
