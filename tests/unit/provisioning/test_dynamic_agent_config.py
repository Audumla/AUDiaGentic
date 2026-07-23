from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audiagentic import launcher
from audiagentic.components.session.session_visibility import set_cli_visibility
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.lifecycle.components import install_component
from audiagentic.runtime.harness.pi.install import request_runtime_reload
from audiagentic.runtime.harness.pi.install.config import (
    _build_settings_config,
    materialize_agent_config,
)
from audiagentic.runtime.harness.system_prompt import (
    build_system_prompt_injections as build_system_md_injections,
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


def test_materialize_agent_config_rebuilds_mcp_from_installed_components(
    tmp_path: Path,
) -> None:
    """Native Pi config contains enabled functional servers, not bootstrap management."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}
    mcp_path = project_root / ".audiagentic" / "mcp.json"

    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    initial = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "ag-lsp-mgmt" not in initial["mcpServers"]

    install_component("coding-lsp", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    updated = json.loads(mcp_path.read_text(encoding="utf-8"))

    assert "ag-lsp" in updated["mcpServers"]
    assert "ag-lsp-mgmt" not in updated["mcpServers"]


def test_agents_functional_servers_are_in_native_harness_mcp_config(
    tmp_path: Path,
) -> None:
    """Native harness config receives provider-facing agent resolution and gateway servers."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}
    mcp_path = project_root / ".audiagentic" / "mcp.json"

    install_component("agents", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads(mcp_path.read_text(encoding="utf-8"))

    assert {"ag-agents", "ag-agents-gateway"} <= set(payload["mcpServers"])
    assert "ag-agents-mgmt" not in payload["mcpServers"]


def test_management_only_provider_server_is_not_in_native_mcp_config(
    tmp_path: Path,
) -> None:
    """Bootstrap management servers are not projected into native functional config."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}
    mcp_path = project_root / ".audiagentic" / "mcp.json"

    install_component("providers", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads(mcp_path.read_text(encoding="utf-8"))

    assert "ag-providers-mgmt" not in payload["mcpServers"]


def test_ledger_component_uses_optional_server_module_in_mcp_config(
    tmp_path: Path,
) -> None:
    """The functional ledger server appears; its bootstrap management peer does not."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}
    mcp_path = project_root / ".audiagentic" / "mcp.json"

    install_component("agent-ledger", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads(mcp_path.read_text(encoding="utf-8"))

    assert "ag-ledger" in payload["mcpServers"]
    assert "ag-ledger-mgmt" not in payload["mcpServers"]


def test_harness_mcp_config_uses_runtime_python_command(
    tmp_path: Path,
) -> None:
    """Pi adapter reads mcp.json directly; AUDiaGentic placeholders cannot be used there."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}
    mcp_path = project_root / ".audiagentic" / "mcp.json"

    install_component("agent-ledger", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads(mcp_path.read_text(encoding="utf-8"))

    command = payload["mcpServers"]["ag-ledger"]["command"]
    assert command == str(sys.executable)
    assert command != "__AUDIAGENTIC_PYTHON__"


def test_component_mcp_metadata_loads_from_yaml() -> None:
    register_all_components()

    project_decl = get_mcp_server_declaration("project", "ag-project-mgmt")
    session_decl = get_mcp_server_declaration("session", "ag-session-mgmt")
    ledger_decl = get_mcp_server_declaration("agent-ledger", "ag-ledger")

    assert project_decl is not None
    assert "list_components" in project_decl.instructions
    assert "project_status" in project_decl.tool_descriptions

    assert session_decl is not None
    assert "CLI visibility controls" in session_decl.instructions
    assert "set_cli_visibility" in session_decl.tool_descriptions

    assert ledger_decl is not None
    assert ledger_decl.module == "audiagentic.components.ledger.ledger_mcp"


def test_component_install_refreshes_materialized_agent_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()

    refresh_calls: list[tuple[Path, Path]] = []
    reload_calls: list[tuple[Path, str, str | None]] = []

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
        "audiagentic.runtime.harness.pi.install.refresh_materialized_agent_config",
        lambda target, project_root=None: refresh_calls.append((target, project_root)),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install.request_runtime_reload",
        lambda project_root, *, reason, component_id=None, has_mcp_servers=True: reload_calls.append(
            (project_root, reason, component_id)
        ),
    )

    args = argparse.Namespace(component_cmd="install", component_id="coding-lsp")

    rc = launcher._cmd_component(args, project_root)

    assert rc == 0
    assert refresh_calls
    assert all(call == (harness_root, project_root) for call in refresh_calls)
    assert reload_calls
    assert all(call == (project_root, "component-installed", "coding-lsp") for call in reload_calls)


def test_request_runtime_reload_writes_marker(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    marker = request_runtime_reload(
        project_root,
        reason="component-enabled",
        component_id="coding-lsp",
    )

    assert marker == project_root / ".audiagentic" / "runtime" / "harness" / "reload-request.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["reason"] == "component-enabled"
    assert payload["component_id"] == "coding-lsp"
    assert payload["requested_at"].endswith("Z")


def test_build_settings_config_includes_tool_visibility_flag(tmp_path: Path) -> None:
    target = tmp_path / "harness"
    target.mkdir()

    settings = _build_settings_config(
        {
            "ui": {
                "hide_thinking_block": True,
                "hide_tool_use": False,
            }
        },
        target,
    )

    assert settings["hideThinkingBlock"] is True
    assert settings["audiagenticHideToolUse"] is False


def test_set_cli_visibility_updates_project_config_and_requests_reload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    cfg_path = project_root / ".audiagentic" / "config" / "harness" / "ag.yaml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("ui:\n  hide_thinking_block: false\n  hide_tool_use: false\n", encoding="utf-8")
    harness_root = tmp_path / "harness"
    harness_root.mkdir()

    refresh_calls: list[tuple[Path, Path]] = []
    reload_calls: list[tuple[Path, str]] = []

    monkeypatch.setattr(
         "audiagentic.foundation.paths.home.global_harness_runtime",
        lambda: harness_root,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install.refresh_materialized_agent_config",
        lambda target, project_root=None: refresh_calls.append((target, project_root)),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install.request_runtime_reload",
        lambda project_root, *, reason, component_id=None, has_mcp_servers=True: reload_calls.append((project_root, reason)),
    )
    monkeypatch.setattr(
        "audiagentic.components.session.session_visibility.effective_cli_visibility",
        lambda project_root: {
            "show_thinking_blocks": False,
            "show_tool_blocks": True,
        },
    )

    result = set_cli_visibility(
        project_root=project_root,
        show_thinking_blocks=False,
        show_tool_blocks=True,
        scope="project",
    )

    payload = cfg_path.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "hide_thinking_block: true" in payload
    assert "hide_tool_use: false" in payload
    assert refresh_calls == [(harness_root, project_root)]
    assert reload_calls == [(project_root, "session-ui-visibility-updated")]
