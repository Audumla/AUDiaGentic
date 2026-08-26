"""Pi ACP launch adapter contract tests."""
from __future__ import annotations

import os

import pytest

from audiagentic.components.providers.services.execution.execution import load_acp_launch_builder

# The pi-acp bridge is resolved from the system install (PATH, else npx), not an
# embedded copy. Tests stub that resolver rather than a managed-runtime path.
_RESOLVER = "audiagentic.components.providers.adapters.pi.system.resolve_system_pi_acp_argv"


def test_pi_exposes_acp_launch_builder():
    assert load_acp_launch_builder("pi") is not None


def test_pi_launch_uses_system_bridge_and_admitted_model(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.pi.acp as pi_acp

    monkeypatch.setattr(_RESOLVER, lambda version=None: ["/usr/bin/pi-acp"])

    request_root = tmp_path / "request-a"
    project = tmp_path / "project"
    project.mkdir()
    launch = pi_acp.build_acp_launch(
        project,
        model_id="model",
        model_selector="local/model",
        request_runtime_root=request_root,
    )

    assert launch.executable == "/usr/bin/pi-acp"
    assert launch.args == (
        "--cwd", str((tmp_path / "project").resolve()),
        "--session-dir", str((request_root / "pi" / "sessions").resolve()),
    )
    assert launch.initial_config_options == (("model", "local/model"),)
    assert launch.environment["PI_CODING_AGENT_DIR"] == str((request_root / "pi" / "agent").resolve())
    assert "HOME" not in launch.environment or os.name == "nt"


def test_pi_launch_uses_npx_prefix_when_no_direct_bridge(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.pi.acp as pi_acp

    # npx-style resolution: executable is npx, the package name leads the args.
    monkeypatch.setattr(_RESOLVER, lambda version=None: ["/usr/bin/npx", "--yes", "pi-acp"])
    launch = pi_acp.build_acp_launch(tmp_path / "project")

    assert launch.executable == "/usr/bin/npx"
    assert launch.args[:3] == ("--yes", "pi-acp", "--cwd")


def test_pi_launch_request_roots_are_distinct(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.pi.acp as pi_acp

    monkeypatch.setattr(_RESOLVER, lambda version=None: ["/usr/bin/pi-acp"])
    project = tmp_path / "project"
    first = pi_acp.build_acp_launch(project, request_runtime_root=tmp_path / "request-a")
    second = pi_acp.build_acp_launch(project, request_runtime_root=tmp_path / "request-b")

    assert first.environment["PI_CODING_AGENT_DIR"] != second.environment["PI_CODING_AGENT_DIR"]
    assert first.args[first.args.index("--session-dir") + 1] != second.args[second.args.index("--session-dir") + 1]
    assert first.args[first.args.index("--cwd") + 1] == second.args[second.args.index("--cwd") + 1]


def test_pi_launch_fails_when_system_bridge_is_missing(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.pi.acp as pi_acp

    monkeypatch.setattr(_RESOLVER, lambda version=None: None)

    with pytest.raises(Exception, match="pi-acp bridge not found"):
        pi_acp.build_acp_launch(tmp_path / "project")
