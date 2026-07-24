"""Public Pi harness lifecycle in an isolated home.

The test deliberately keeps npm outside the contract: a tiny shim stands in
for the package download while every AUDiaGentic-owned path, materializer,
CLI dispatch and cleanup action runs unchanged.  It therefore works locally
without network credentials and is also the Docker user-path gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from audiagentic.launcher import _main


def _stub_pi_download(monkeypatch) -> None:
    """Keep the test about our lifecycle, not npm availability."""
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install._provision_embedded_rig",
        lambda *_a, **_kw: None,
    )


def test_launch_fails_loud_when_config_refresh_fails(tmp_path: Path, monkeypatch) -> None:
    """A failed launch-time config rebuild must abort, not launch stale."""
    project = tmp_path / "project"
    project.mkdir()

    monkeypatch.setenv("AUDIAGENTIC_AUTO_UPDATE_ENABLED", "false")
    monkeypatch.setenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", "never")
    monkeypatch.setattr(
        "audiagentic.runtime.harness.resolution.harness_cli_available",
        lambda _harness_type: "/usr/bin/pi",
    )

    def _boom(*_a, **_kw):
        raise RuntimeError("config build blew up")

    monkeypatch.setattr("audiagentic.runtime.harness.refresh_materialized_agent_config", _boom)

    launched: list[int] = []
    monkeypatch.setattr(
        "audiagentic.runtime.harness.build_global_context",
        lambda **_kw: launched.append(1) or SimpleNamespace(manages_rig=False),
    )
    monkeypatch.setattr("audiagentic.runtime.harness.run_agent", lambda *_a, **_kw: launched.append(1) or 0)

    assert _main(["--project", str(project), "--prompt", "hello"]) == 1
    assert not launched, "harness must not start when the config rebuild fails"


def test_bootstrap_refresh_launch_and_cleanup_materialize_owned_paths(
    tmp_path: Path, monkeypatch
) -> None:
    """The documented commands materialize config, refresh it on launch and clean safely."""
    project = tmp_path / "project"
    from audiagentic.foundation.paths.home import global_harness_runtime

    runtime = global_harness_runtime()
    project.mkdir()
    _stub_pi_download(monkeypatch)

    # Install a real component so MCP collection exercises the normal
    # descriptor/lifecycle path rather than a hand-built config fixture.
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.lifecycle.components import install_component

    register_all_components()
    assert install_component("agent-planning", project)["ok"] is True

    assert _main(["--project", str(project), "bootstrap", "--target", str(runtime)]) == 0
    # No embedded harness CLI is installed anymore — bootstrap only materializes
    # the agent config + rig backend area.
    assert not (runtime / "cli").exists()
    assert (runtime / "agent" / "models.json").is_file()
    assert (runtime / "agent" / "settings.json").is_file()
    assert (runtime / "SYSTEM.md").is_file()

    mcp_path = project / ".audiagentic" / "mcp.json"
    installed_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    # ag-planning (propagate: providers) → projected to harness mcp.json
    assert "ag-planning" in installed_mcp["mcpServers"], (
        f"Expected ag-planning in project mcp.json. Got: {list(installed_mcp['mcpServers'].keys())}"
    )
    # ag-planning-mgmt (propagate: audiagentic) → NOT projected to harness
    assert "ag-planning-mgmt" not in installed_mcp["mcpServers"], (
        f"ag-planning-mgmt should NOT be in project mcp.json (propagate: audiagentic). Got: {list(installed_mcp['mcpServers'].keys())}"
    )

    # Bootstrap is repeatable and preserves the harness's large/user-owned area.
    sentinel = runtime / "rig" / "bin" / "models" / "user-model.gguf"
    sentinel.write_bytes(b"user-owned")
    assert _main(["--project", str(project), "bootstrap", "--target", str(runtime)]) == 0
    assert sentinel.read_bytes() == b"user-owned"

    # Launch must refresh the same project-local MCP projection before the
    # harness is invoked.  Stub only the external runner boundary. The harness
    # CLI is a system install; stub its presence so this gate is network- and
    # host-independent.
    monkeypatch.setenv("AUDIAGENTIC_AUTO_UPDATE_ENABLED", "false")
    monkeypatch.setenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", "never")
    monkeypatch.setattr(
        "audiagentic.runtime.harness.resolution.harness_cli_available",
        lambda _harness_type: "/usr/bin/pi",
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.build_global_context",
        lambda **_kw: SimpleNamespace(manages_rig=False),
    )
    monkeypatch.setattr("audiagentic.runtime.harness.env_flag", lambda *_a: False)
    monkeypatch.setattr("audiagentic.runtime.harness.run_agent", lambda *_a, **_kw: 0)
    monkeypatch.setattr("audiagentic.runtime.harness.translate_agent_args", lambda _params: [])
    assert _main(["--project", str(project), "--prompt", "hello"]) == 0
    refreshed_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    # ag-planning survives launch-time refresh
    assert "ag-planning" in refreshed_mcp["mcpServers"]
    assert "ag-planning-mgmt" not in refreshed_mcp["mcpServers"]

    assert _main(["--project", str(project), "cleanup", "--target", str(runtime)]) == 0
    assert not (runtime / "cli").exists()
    assert not (runtime / "agent").exists()
    assert sentinel.read_bytes() == b"user-owned"
    assert mcp_path.exists(), "project-owned MCP configuration must survive cleanup"
