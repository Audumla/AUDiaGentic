from __future__ import annotations

import argparse
import json
from pathlib import Path

from audiagentic import launcher
from audiagentic.components.session.session_visibility import set_cli_visibility
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.runtime.harness.pi.install import request_runtime_reload
from audiagentic.runtime.harness.pi.install.config import (
    _build_settings_config,
    materialize_agent_config,
)
from audiagentic.runtime.harness.system_prompt import (
    build_system_prompt_injections as build_system_md_injections,
)
from audiagentic.runtime.lifecycle.components import install_component


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

    assert "MCP tools" in injections
    assert "Available components" in injections
    assert "installed/enabled" in injections["Available components"]
    assert "`providers`" in injections["Available components"]
    assert "not installed" in injections["Available components"]


def test_materialize_agent_config_rebuilds_mcp_from_installed_components(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}

    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    initial = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))
    assert "ag-lsp-mgmt" not in initial["mcpServers"]

    install_component("coding-lsp", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    updated = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))

    assert "ag-lsp-mgmt" in updated["mcpServers"]


def test_providers_component_uses_optional_server_module_in_mcp_config(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}

    install_component("providers", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))

    providers = payload["mcpServers"]["ag-providers-mgmt"]
    assert providers["command"] == "audiagentic"
    assert providers["args"] == [
        "mcp",
        "audiagentic.components.providers.providers_mcp",
    ]


def test_ledger_component_uses_optional_server_module_in_mcp_config(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}

    install_component("agent-ledger", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))

    ledger = payload["mcpServers"]["ag-ledger"]
    assert ledger["command"] == "audiagentic"
    assert ledger["args"] == [
        "mcp",
        "audiagentic.components.ledger.ledger_mcp",
    ]


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
    (harness_root / "cli" / "node_modules" / ".bin").mkdir(parents=True)

    refresh_calls: list[tuple[Path, Path]] = []
    reload_calls: list[tuple[Path, str, str | None]] = []

    monkeypatch.setattr(
        "audiagentic.runtime.home.global_harness_runtime",
        lambda: harness_root,
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
        "audiagentic.runtime.home.global_harness_runtime",
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
