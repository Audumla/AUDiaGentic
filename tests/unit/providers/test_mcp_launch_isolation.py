from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.adapters.opencode import acp as opencode_acp
from audiagentic.components.providers.adapters.opencode import mcp_surface as opencode_surface
from audiagentic.components.providers.adapters.pi import acp as pi_acp
from audiagentic.components.providers.adapters.pi import mcp_surface as pi_surface
from audiagentic.components.providers.contracts.mcp_launch_surface import (
    McpLaunchServerEntry,
    McpLaunchSurfaceRequest,
)


def _request(project: Path, runtime: Path, name: str = "selected") -> McpLaunchSurfaceRequest:
    return McpLaunchSurfaceRequest(
        project_root=str(project),
        runtime_root=str(runtime),
        entries=(McpLaunchServerEntry(name=name, command="server", args=("--stdio",)),),
    )


def test_pi_materializes_distinct_request_owned_configs(tmp_path, monkeypatch) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    package_root = tmp_path / "packages"
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.pi.system.resolve_system_pi_mcp_adapter",
        lambda: adapter,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.system_probe.resolve_system_package_root",
        lambda _cli: package_root,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.pi.mcp_exclusive_patch.apply_mcp_exclusive_patch",
        lambda _root: True,
    )
    monkeypatch.setattr("shutil.which", lambda name: "pi" if name == "pi" else None)

    first = pi_surface.prepare_mcp_surface(_request(tmp_path, tmp_path / "job-a", "a"))
    second = pi_surface.prepare_mcp_surface(_request(tmp_path, tmp_path / "job-b", "b"))

    assert first.applied_isolation == second.applied_isolation == "exact"
    first_path = Path(first.extra_args[first.extra_args.index("--mcp-config") + 1])
    second_path = Path(second.extra_args[second.extra_args.index("--mcp-config") + 1])
    assert first_path != second_path
    assert set(json.loads(first_path.read_text())["mcpServers"]) == {"a"}
    assert set(json.loads(second_path.read_text())["mcpServers"]) == {"b"}


def test_pi_acp_uses_request_owned_wrapper(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pi_acp, "_system_pi_acp_argv", lambda: ["pi-acp"])
    monkeypatch.setattr(pi_acp.shutil, "which", lambda name: "C:/tools/pi.cmd" if name == "pi" else None)
    surface = type("Surface", (), {"applied_isolation": "exact", "extra_args": ("--mcp-config", "x.json", "--mcp-exclusive")})()

    launch = pi_acp.build_acp_launch(
        tmp_path,
        model_id="model",
        request_runtime_root=tmp_path / "runtime",
        mcp_surface=surface,
    )

    wrapper = Path(launch.environment["PI_ACP_PI_COMMAND"])
    assert wrapper.is_file()
    assert "--mcp-exclusive" in wrapper.read_text()
    assert launch.environment["PI_CODING_AGENT_DIR"].startswith(str(tmp_path / "runtime"))


def test_opencode_surface_isolates_global_config_and_plugins(tmp_path) -> None:
    project_config = tmp_path / ".opencode" / "opencode.json"
    project_config.parent.mkdir()
    project_config.write_text(json.dumps({"mcp": {"ambient": {"type": "local"}}}))

    result = opencode_surface.prepare_mcp_surface(_request(tmp_path, tmp_path / "runtime"))
    environment = dict(result.extra_env)
    document = json.loads(environment["OPENCODE_CONFIG_CONTENT"])

    assert result.applied_isolation == "exact"
    assert environment["XDG_CONFIG_HOME"].startswith(str(tmp_path / "runtime"))
    assert document["plugin"] == []
    assert document["mcp"]["ambient"] == {"enabled": False}
    assert document["mcp"]["selected"]["enabled"] is True


def test_opencode_acp_composes_model_and_mcp_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(opencode_acp, "require_executable", lambda *_args: "opencode")
    surface = opencode_surface.prepare_mcp_surface(_request(tmp_path, tmp_path / "runtime"))

    launch = opencode_acp.build_acp_launch(
        tmp_path,
        model_id="provider/model",
        request_runtime_root=tmp_path / "runtime",
        mcp_surface=surface,
    )
    document = json.loads(launch.environment["OPENCODE_CONFIG_CONTENT"])

    assert document["model"] == "provider/model"
    assert set(document["mcp"]) == {"selected"}
    assert document["plugin"] == []
    assert launch.environment["XDG_CONFIG_HOME"].startswith(str(tmp_path / "runtime"))
