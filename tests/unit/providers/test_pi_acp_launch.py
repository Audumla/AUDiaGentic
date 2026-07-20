"""Pi ACP launch adapter contract tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from audiagentic.components.providers.services.execution import load_acp_launch_builder


def _runtime(root: Path) -> Path:
    bridge = root / "cli" / "node_modules" / ".bin" / (
        "pi-acp.cmd" if os.name == "nt" else "pi-acp"
    )
    bridge.parent.mkdir(parents=True)
    bridge.touch()
    return root


def test_pi_exposes_acp_launch_builder():
    assert load_acp_launch_builder("pi") is not None


def test_pi_launch_uses_managed_bridge_and_model(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.pi.acp as pi_acp

    runtime = _runtime(tmp_path / "harness")
    monkeypatch.setattr(pi_acp, "global_harness_runtime", lambda: runtime)

    request_root = tmp_path / "request-a"
    launch = pi_acp.build_acp_launch(
        tmp_path / "project", model_id="local/model", request_runtime_root=request_root
    )

    assert launch.executable == str(runtime / "cli" / "node_modules" / ".bin" / (
        "pi-acp.cmd" if os.name == "nt" else "pi-acp"
    ))
    assert launch.args == (
        "--cwd", str((tmp_path / "project").resolve()),
        "--session-dir", str((request_root / "pi" / "sessions").resolve()),
        "--model", "local/model",
    )
    assert launch.environment["PI_CODING_AGENT_DIR"] == str((request_root / "pi" / "agent").resolve())
    assert "HOME" not in launch.environment or os.name == "nt"


def test_pi_launch_request_roots_are_distinct(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.pi.acp as pi_acp

    runtime = _runtime(tmp_path / "harness")
    monkeypatch.setattr(pi_acp, "global_harness_runtime", lambda: runtime)
    project = tmp_path / "project"
    first = pi_acp.build_acp_launch(project, request_runtime_root=tmp_path / "request-a")
    second = pi_acp.build_acp_launch(project, request_runtime_root=tmp_path / "request-b")

    assert first.environment["PI_CODING_AGENT_DIR"] != second.environment["PI_CODING_AGENT_DIR"]
    assert first.args[first.args.index("--session-dir") + 1] != second.args[second.args.index("--session-dir") + 1]
    assert first.args[first.args.index("--cwd") + 1] == second.args[second.args.index("--cwd") + 1]


def test_pi_launch_fails_when_managed_bridge_is_missing(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.pi.acp as pi_acp

    monkeypatch.setattr(pi_acp, "global_harness_runtime", lambda: tmp_path / "harness")

    with pytest.raises(Exception, match="Managed Pi ACP bridge is not installed"):
        pi_acp.build_acp_launch(tmp_path / "project")
