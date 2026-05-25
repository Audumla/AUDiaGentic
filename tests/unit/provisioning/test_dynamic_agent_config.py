from __future__ import annotations

import argparse
import json
from pathlib import Path

from audiagentic import launcher
from audiagentic.components.core.session_server import _set_cli_visibility
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.runtime.harness.pi.install import request_runtime_reload
from audiagentic.runtime.harness.pi.install.config import (
    _build_settings_config,
    materialize_agent_config,
)
from audiagentic.runtime.lifecycle.components import install_component
from audiagentic.runtime.mcp_config_builder import build_system_md_injections


def test_build_system_md_injections_uses_explicit_project_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    other_root = tmp_path / "other"
    project_root.mkdir()
    other_root.mkdir()

    register_all_components()
    install_component("planning", project_root)
    monkeypatch.chdir(other_root)

    injections = build_system_md_injections(project_root)

    assert "What you can do" in injections
    assert "Available components" in injections
    assert "mcp_planning_status" in injections["What you can do"]
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
    harness_cfg = {"model": "test-model"}

    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    initial = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))
    assert "audiagentic-planning" not in initial["mcpServers"]

    install_component("planning", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    updated = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))

    assert "audiagentic-planning" in updated["mcpServers"]


def test_providers_component_uses_optional_server_module_in_mcp_config(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"model": "test-model"}

    install_component("providers", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))

    providers = payload["mcpServers"]["audiagentic-providers"]
    assert providers["args"] == [
        "-m",
        "audiagentic.components.optional.providers.server",
    ]


def test_planning_component_uses_optional_server_module_in_mcp_config(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"model": "test-model"}

    install_component("planning", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))

    planning = payload["mcpServers"]["audiagentic-planning"]
    assert planning["args"] == [
        "-m",
        "audiagentic.components.optional.planning.server",
    ]


def test_ledger_component_uses_optional_server_module_in_mcp_config(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    register_all_components()
    harness_cfg = {"model": "test-model"}

    install_component("agent-ledger", project_root)
    materialize_agent_config(harness_root, harness_cfg, project_root=project_root)
    payload = json.loads((harness_root / "agent" / "mcp.json").read_text(encoding="utf-8"))

    ledger = payload["mcpServers"]["audiagentic-release-please"]
    assert ledger["args"] == [
        "-m",
        "audiagentic.components.optional.ledger.server",
    ]


def test_component_mcp_metadata_loads_from_yaml() -> None:
    register_all_components()

    project_decl = get_mcp_server_declaration("project", "audiagentic-project")
    session_decl = get_mcp_server_declaration("session", "audiagentic-session")
    planning_decl = get_mcp_server_declaration("planning", "audiagentic-planning")
    ledger_decl = get_mcp_server_declaration("agent-ledger", "audiagentic-release-please")

    assert project_decl is not None
    assert "list_components" in project_decl.instructions
    assert "project_status" in project_decl.tool_descriptions

    assert session_decl is not None
    assert "CLI visibility controls" in session_decl.instructions
    assert "set_cli_visibility" in session_decl.tool_descriptions

    assert planning_decl is not None
    assert planning_decl.module == "audiagentic.components.optional.planning.server"
    assert "planning_summary" in planning_decl.tool_descriptions

    assert ledger_decl is not None
    assert ledger_decl.module == "audiagentic.components.optional.ledger.server"
    assert "release_please_status" in ledger_decl.tool_descriptions


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
        lambda project_root, *, reason, component_id=None: reload_calls.append(
            (project_root, reason, component_id)
        ),
    )

    args = argparse.Namespace(component_cmd="install", component_id="planning")

    rc = launcher._cmd_component(args, project_root)

    assert rc == 0
    assert refresh_calls == [(harness_root, project_root)]
    assert reload_calls == [(project_root, "component-installed", "planning")]


def test_request_runtime_reload_writes_marker(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    marker = request_runtime_reload(
        project_root,
        reason="component-enabled",
        component_id="planning",
    )

    assert marker == project_root / ".audiagentic" / "runtime" / "harness" / "reload-request.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["reason"] == "component-enabled"
    assert payload["component_id"] == "planning"
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
        lambda project_root, *, reason, component_id=None: reload_calls.append((project_root, reason)),
    )
    monkeypatch.setattr(
        "audiagentic.components.core.session_server._effective_cli_visibility",
        lambda project_root: {
            "show_thinking_blocks": False,
            "show_tool_blocks": True,
        },
    )

    result = _set_cli_visibility(
        project_root=project_root,
        show_thinking_blocks=False,
        show_tool_blocks=True,
        scope="project",
    )

    cfg_path = project_root / ".audiagentic" / "config" / "harness" / "ag.yaml"
    payload = cfg_path.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "hide_thinking_block: true" in payload
    assert "hide_tool_use: false" in payload
    assert refresh_calls == [(harness_root, project_root)]
    assert reload_calls == [(project_root, "session-ui-visibility-updated")]
