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
    monkeypatch.setattr("audiagentic.runtime.harness.pi.install._c._npm", lambda: "npm")
    monkeypatch.setattr("audiagentic.runtime.harness.pi.install.subprocess.run", lambda *a, **kw: None)
    monkeypatch.setattr("audiagentic.runtime.harness.pi.install._validate_agent_install", lambda _path: None)
    monkeypatch.setattr("audiagentic.runtime.harness.pi.install.apply_lockdown_patches", lambda *a, **kw: None)
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install._provision_embedded_rig",
        lambda *_a, **_kw: None,
    )


def test_install_refresh_launch_and_uninstall_materialize_owned_paths(
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

    assert _main(["--project", str(project), "install", "--target", str(runtime)]) == 0
    assert (runtime / "cli").is_dir()
    assert (runtime / "agent" / "models.json").is_file()
    assert (runtime / "agent" / "settings.json").is_file()
    assert (runtime / "SYSTEM.md").is_file()

    mcp_path = project / ".audiagentic" / "mcp.json"
    installed_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "ag-planning-mgmt" in installed_mcp["mcpServers"]

    # Install is repeatable and preserves the harness's large/user-owned area.
    sentinel = runtime / "rig" / "bin" / "models" / "user-model.gguf"
    sentinel.write_bytes(b"user-owned")
    assert _main(["--project", str(project), "install", "--target", str(runtime)]) == 0
    assert sentinel.read_bytes() == b"user-owned"
    # npm normally creates this executable directory.  The network-free shim
    # above intentionally does not model npm's output beyond this launch gate.
    (runtime / "cli" / "node_modules" / ".bin").mkdir(parents=True)

    # Launch must refresh the same project-local MCP projection before the
    # harness is invoked.  Stub only the external runner boundary.
    monkeypatch.setenv("AUDIAGENTIC_AUTO_UPDATE_ENABLED", "false")
    monkeypatch.setenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", "never")
    monkeypatch.setattr(
        "audiagentic.runtime.harness.build_global_context",
        lambda **_kw: SimpleNamespace(manages_rig=False),
    )
    monkeypatch.setattr("audiagentic.runtime.harness.env_flag", lambda *_a: False)
    monkeypatch.setattr("audiagentic.runtime.harness.run_agent", lambda *_a, **_kw: 0)
    monkeypatch.setattr("audiagentic.runtime.harness.translate_agent_args", lambda _params: [])
    assert _main(["--project", str(project), "--prompt", "hello"]) == 0
    refreshed_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "ag-planning-mgmt" in refreshed_mcp["mcpServers"]

    assert _main(["--project", str(project), "uninstall", "--target", str(runtime)]) == 0
    assert not (runtime / "cli").exists()
    assert not (runtime / "agent").exists()
    assert sentinel.read_bytes() == b"user-owned"
    assert mcp_path.exists(), "project-owned MCP configuration must survive harness uninstall"
