"""E2E: component MCP servers via JSON-RPC subprocess.

Starts session/providers/planning/release MCP servers as subprocesses and
verifies they expose the expected tools and respond to a basic status call.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
_INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def _mcp(module: str, *messages: dict, project_root: Path, extra_args: list[str] | None = None, timeout: int = 30) -> list[dict]:
    payload = "\n".join(json.dumps(m) for m in [_INIT, _INITIALIZED, *messages]) + "\n"
    env = dict(os.environ)
    env["AUDIAGENTIC_REPO_ROOT"] = str(project_root)
    command = [sys.executable, "-m", module]
    if extra_args:
        command.extend(extra_args)
    proc = subprocess.run(
        command,
        input=payload,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    assert proc.returncode == 0, f"MCP server {module} rc={proc.returncode}\n{proc.stderr}"
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def _tools_list(module: str, project_root: Path, extra_args: list[str] | None = None) -> set[str]:
    responses = _mcp(
        module,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        project_root=project_root,
        extra_args=extra_args,
    )
    resp = next(r for r in responses if r.get("id") == 2)
    return {tool["name"] for tool in resp["result"]["tools"]}


def _call(
    module: str,
    tool: str,
    args: dict,
    *,
    project_root: Path,
    msg_id: int = 2,
    extra_args: list[str] | None = None,
    timeout: int = 30,
) -> dict | list:
    responses = _mcp(
        module,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        },
        project_root=project_root,
        extra_args=extra_args,
        timeout=timeout,
    )
    resp = next(r for r in responses if r.get("id") == msg_id)
    assert "error" not in resp, f"tool {tool!r} error: {resp['error']}"
    blocks = resp["result"]["content"]
    parsed = [json.loads(block["text"]) for block in blocks]
    return parsed if len(parsed) > 1 else parsed[0]


def _call_keepalive(
    module: str,
    tool: str,
    args: dict,
    *,
    project_root: Path,
    msg_id: int = 2,
    timeout: int = 120,
) -> dict | list:
    env = dict(os.environ)
    env["AUDIAGENTIC_REPO_ROOT"] = str(project_root)
    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    for message in (
        _INIT,
        _INITIALIZED,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": args,
                "_meta": {"progressToken": f"test-{msg_id}"},
            },
        },
    ):
        proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()

    responses: list[dict] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        payload = json.loads(line)
        responses.append(payload)
        if payload.get("id") == msg_id:
            break

    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=5)

    resp = next(r for r in responses if r.get("id") == msg_id)
    assert "error" not in resp, f"tool {tool!r} error: {resp['error']}"
    blocks = resp["result"]["content"]
    parsed = [json.loads(block["text"]) for block in blocks]
    return parsed if len(parsed) > 1 else parsed[0]


def test_session_server_exposes_expected_tools(tmp_path: Path) -> None:
    names = _tools_list(
        "audiagentic.components.core.session_server",
        tmp_path,
        extra_args=["--readonly", "--smoke-only"],
    )
    assert {
        "status",
        "config",
        "set_auto_update",
        "cli_visibility",
        "set_cli_visibility",
    }.issubset(names)


def test_session_server_status_returns_environment(tmp_path: Path) -> None:
    result = _call(
        "audiagentic.components.core.session_server",
        "status",
        {},
        project_root=tmp_path,
        extra_args=["--readonly", "--smoke-only"],
    )
    payload = result if isinstance(result, dict) else result[0]
    assert payload["environment"]["repo_root"] == str(tmp_path)
    assert "versions" in payload


def test_project_server_exposes_expected_tools(tmp_path: Path) -> None:
    names = _tools_list("audiagentic.components.core.project_server", tmp_path)
    assert {
        "project_status",
        "list_components",
        "install_component_tool",
        "uninstall_component_tool",
        "enable_component_tool",
        "disable_component_tool",
    }.issubset(names)


def test_project_server_lists_optional_components_not_installed(tmp_path: Path) -> None:
    result = _call(
        "audiagentic.components.core.project_server",
        "list_components",
        {},
        project_root=tmp_path,
    )
    payload = result if isinstance(result, list) else [result]
    components = {component["component_id"]: component for component in payload}
    assert "providers" in components
    assert components["providers"]["status"] == "not-installed"
    assert components["providers"]["enabled"] is None


def test_providers_server_exposes_expected_tools(tmp_path: Path) -> None:
    names = _tools_list("audiagentic.components.optional.providers.server", tmp_path)
    assert {
        "list_providers",
        "provider_status",
        "list_provider_descriptors",
        "interrogate_provider",
        "set_provider_enabled",
        "reconcile_all_providers",
    }.issubset(names)


def test_providers_server_lists_known_providers(tmp_path: Path) -> None:
    result = _call(
        "audiagentic.components.optional.providers.server",
        "list_providers",
        {},
        project_root=tmp_path,
    )
    payload = result if isinstance(result, dict) else result[0]
    provider_ids = {provider["provider_id"] for provider in payload["providers"]}
    assert "codex" in provider_ids
    assert "gemini" in provider_ids


def test_planning_server_exposes_expected_tools(tmp_path: Path) -> None:
    names = _tools_list("audiagentic.components.optional.planning.server", tmp_path)
    assert {
        "planning_status",
        "planning_summary",
        "planning_index",
        "planning_events",
    }.issubset(names)


def test_planning_server_status_on_fresh_project(tmp_path: Path) -> None:
    result = _call(
        "audiagentic.components.optional.planning.server",
        "planning_status",
        {},
        project_root=tmp_path,
    )
    payload = result if isinstance(result, dict) else result[0]
    assert payload["installed"] is False


def test_release_please_server_exposes_expected_tools(tmp_path: Path) -> None:
    names = _tools_list(
        "audiagentic.components.optional.release.release_please.release_please_mcp",
        tmp_path,
    )
    assert {
        "release_please_status",
        "install_release_please",
        "update_release_please_workflow",
    }.issubset(names)


def test_release_please_server_status_returns_payload(tmp_path: Path) -> None:
    result = _call(
        "audiagentic.components.optional.release.release_please.release_please_mcp",
        "release_please_status",
        {},
        project_root=tmp_path,
    )
    payload = result if isinstance(result, dict) else result[0]
    assert isinstance(payload, dict)


def test_session_server_update_embedded_rig(tmp_path: Path) -> None:
    result = _call_keepalive(
        "audiagentic.components.core.session_server",
        "update_embedded_rig",
        {},
        project_root=tmp_path,
        timeout=120,
    )
    payload = result if isinstance(result, dict) else result[0]
    assert payload["ok"] is True
    assert "output" in payload


def test_session_server_detects_active_embedded_rig_profile(monkeypatch) -> None:
    from audiagentic.components.core.session_server import _active_embedded_rig_profile

    monkeypatch.setenv("AUDIAGENTIC_RIG_TYPE", "embedded")
    monkeypatch.setenv("AUDIAGENTIC_RIG_PROFILE", "qwen3.5-2b-q4_k_s")
    assert _active_embedded_rig_profile() == "qwen3.5-2b-q4_k_s"


def test_update_embedded_rig_works_directly(tmp_path: Path) -> None:
    """Test the update_binaries work function directly (avoids MCP subprocess timeout)."""
    import contextlib
    import io

    # Set harness home for the test
    import os

    from audiagentic.foundation.output import ComponentOutputEvent
    from audiagentic.runtime.home import global_harness_runtime
    from audiagentic.runtime.rig.embedded.update_binaries import update_binaries as _update
    os.environ["AUDIAGENTIC_HOME"] = str(tmp_path / ".audiagentic")

    out = io.StringIO()
    events = []

    def _sink(event: ComponentOutputEvent) -> None:
        events.append(event)

    harness = global_harness_runtime()
    with contextlib.redirect_stdout(out):
        _update(runtime_dir=harness)
    _sink(ComponentOutputEvent(message=out.getvalue().strip()))

    assert len(events) > 0
    assert "llama-server" in events[-1].message or "Installed" in events[-1].message or "up to date" in events[-1].message
