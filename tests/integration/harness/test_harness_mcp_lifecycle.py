"""Integration tests: harness MCP config across component lifecycle, per harness type.

The provider surface lifecycle suite covers the *provider* projection
(.opencode/opencode.json, .codex/config.toml, ...). This suite covers the
*harness* materialization path: collect_component_mcp_entries → the active harness's
MCP config file, for every harness implementation — and, separately, that the
real lifecycle-event chain (disable_component → event bus → harness subscriber
→ refresh) rewrites that config without any manual refresh call. Regression
guard for disabled components' MCP tools remaining live in a running harness.

Skipped unless AUDIAGENTIC_DOCKER_TESTS=1 (real install/materialize workflow).
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="harness MCP lifecycle tests require Docker isolation",
    ),
    pytest.mark.no_parallel,
]

from tests.integration.lifecycle.harness import (
    component_sandbox,
    disable_component,
    enable_component,
    install_with_deps,
    uninstall_component,
)

from audiagentic.foundation.components.registry import all_descriptors

_HARNESS_TYPES = ["pi", "opencode"]
_COMPONENTS = ["agent-ledger", "agent-planning", "source-control"]


def _harness_mcp_server_names(component_id: str) -> set[str]:
    """Expected harness-propagated MCP server names for a component."""
    desc = all_descriptors().get(component_id)
    if desc is None:
        return set()
    names: set[str] = set()
    for ms in (desc.mcp_servers or []):
        if "audiagentic" in ms.propagate:
            names.add(ms.name)
    for ms in (desc.external_mcp_servers or []):
        # External MCP recipes materialize only when their declared executable
        # is actually available.  This mirrors the public capability contract:
        # a missing optional host tool must be absent, not emitted as a broken
        # server entry.
        if "audiagentic" in ms.propagate and all(shutil.which(requirement) for requirement in ms.requires):
            names.add(ms.name)
    return names


def _write_harness_override(repo: Path, harness_type: str) -> None:
    cfg_path = repo / ".audiagentic" / "config" / "harness" / "ag.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        yaml.dump({"harness": {"type": harness_type}}), encoding="utf-8"
    )


def _refresh(repo: Path, runtime_target: Path) -> None:
    from audiagentic.runtime.harness import refresh_materialized_agent_config

    refresh_materialized_agent_config(runtime_target, project_root=repo)


def _servers_in_harness_config(repo: Path) -> set[str]:
    from audiagentic.runtime.harness import mcp_config_path, read_mcp_config

    path = mcp_config_path(project_root=repo)
    if not path.exists():
        return set()
    return set(read_mcp_config(path).keys())


@pytest.mark.parametrize("harness_type", _HARNESS_TYPES)
@pytest.mark.parametrize("component_id", _COMPONENTS)
def test_harness_mcp_follows_component_lifecycle(
    harness_type: str, component_id: str, tmp_path: Path
) -> None:
    """Install → present; disable → pruned; enable → back; uninstall → pruned.

    Exercises the real harness facade (materialize + format handlers) for each
    harness type via the project-local harness.type override.
    """
    expected = _harness_mcp_server_names(component_id)
    if not expected:
        pytest.skip(f"{component_id} has no audiagentic-propagated MCP servers")

    with component_sandbox(tmp_path, f"harness-mcp-{harness_type}-{component_id}") as sb:
        _write_harness_override(sb.repo, harness_type)
        runtime_target = sb.artifacts / "harness-runtime"
        install_with_deps("project", sb.repo)
        install_with_deps(component_id, sb.repo)

        _refresh(sb.repo, runtime_target)
        present = _servers_in_harness_config(sb.repo)
        assert expected <= present, (
            f"[{harness_type}] {component_id}: servers {expected - present} missing "
            f"after install. Present: {present}"
        )

        disable_component(component_id, sb.repo)
        _refresh(sb.repo, runtime_target)
        still = _servers_in_harness_config(sb.repo) & expected
        assert not still, (
            f"[{harness_type}] {component_id}: servers {still} still in harness "
            f"MCP config after disable"
        )

        enable_component(component_id, sb.repo)
        _refresh(sb.repo, runtime_target)
        present = _servers_in_harness_config(sb.repo)
        assert expected <= present, (
            f"[{harness_type}] {component_id}: servers {expected - present} not "
            f"reinjected after re-enable. Present: {present}"
        )

        uninstall_component(component_id, sb.repo)
        _refresh(sb.repo, runtime_target)
        still = _servers_in_harness_config(sb.repo) & expected
        assert not still, (
            f"[{harness_type}] {component_id}: servers {still} still in harness "
            f"MCP config after uninstall"
        )


# --------------------------------------------------------------------------- #
# Event-driven refresh — the full chain a live harness session relies on
# --------------------------------------------------------------------------- #

def _fake_harness_on_path(name: str, bin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Satisfy the refresh gate (harness_cli_available -> shutil.which). Never executed.

    Both pi and opencode are now resolved from the system PATH — AUDiaGentic no
    longer bundles an embedded harness — so a single stub-on-PATH helper serves
    every harness type.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.mark.parametrize("harness_type", _HARNESS_TYPES)
def test_disable_event_prunes_harness_mcp_without_manual_refresh(
    harness_type: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """disable_component alone must rewrite the harness MCP config.

    This drives the production chain end-to-end: foundation lifecycle publishes
    the event, the runtime.harness subscriber calls
    refresh_harness_config_if_installed, and the materialized MCP config no
    longer lists the disabled component's servers. No test-side refresh calls.
    """
    component_id = "agent-planning"
    expected = _harness_mcp_server_names(component_id)
    assert expected, f"{component_id} must declare audiagentic-propagated servers"

    # Subscription happens at module import time.
    import audiagentic.runtime.harness  # noqa: F401

    with component_sandbox(tmp_path, f"harness-event-{harness_type}") as sb:
        _write_harness_override(sb.repo, harness_type)

        fake_home = sb.root / "home"
        monkeypatch.setenv("AUDIAGENTIC_HOME", str(fake_home))
        _fake_harness_on_path(harness_type, sb.root / "bin", monkeypatch)

        install_with_deps("project", sb.repo)
        install_with_deps(component_id, sb.repo)

        present = _servers_in_harness_config(sb.repo)
        assert expected <= present, (
            f"[{harness_type}] install event did not materialize harness MCP "
            f"config: missing {expected - present}. Present: {present}"
        )

        disable_component(component_id, sb.repo)
        still = _servers_in_harness_config(sb.repo) & expected
        assert not still, (
            f"[{harness_type}] servers {still} still in harness MCP config after "
            f"disable — a running harness would keep serving a disabled "
            f"component's tools"
        )

        enable_component(component_id, sb.repo)
        present = _servers_in_harness_config(sb.repo)
        assert expected <= present, (
            f"[{harness_type}] enable event did not restore harness MCP config: "
            f"missing {expected - present}. Present: {present}"
        )


@pytest.mark.parametrize("harness_type", _HARNESS_TYPES)
def test_harness_mcp_config_is_valid_json_after_lifecycle(
    harness_type: str, tmp_path: Path
) -> None:
    """The materialized MCP config stays parseable across lifecycle churn."""
    component_id = "agent-planning"
    if not _harness_mcp_server_names(component_id):
        pytest.skip(f"{component_id} has no audiagentic-propagated MCP servers")

    from audiagentic.runtime.harness import mcp_config_path

    with component_sandbox(tmp_path, f"harness-json-{harness_type}") as sb:
        _write_harness_override(sb.repo, harness_type)
        runtime_target = sb.artifacts / "harness-runtime"
        install_with_deps("project", sb.repo)
        install_with_deps(component_id, sb.repo)

        for op in (disable_component, enable_component, disable_component):
            op(component_id, sb.repo)
            _refresh(sb.repo, runtime_target)
            path = mcp_config_path(project_root=sb.repo)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(data, dict) and "mcpServers" in data, (
                f"[{harness_type}] malformed harness MCP config after {op.__name__}"
            )
