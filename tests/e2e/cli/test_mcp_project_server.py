"""E2E: MCP project server tools via JSON-RPC subprocess.

Starts the project MCP server as a subprocess and exercises the component lifecycle
tools (list_components, install, enable, disable, project_status, read_project_file).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json
import os
import subprocess

_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
}
_INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def _mcp(*messages: dict, project_root: Path) -> list[dict]:
    payload = "\n".join(json.dumps(m) for m in [_INIT, _INITIALIZED, *messages]) + "\n"
    env = dict(os.environ)
    # Keep AUDIAGENTIC_REPO_ROOT from container env (template root for baseline_sync).
    # The target project is passed via --project-root, not this env var.
    proc = subprocess.run(
        [sys.executable, "-m", "audiagentic.provisioning.mcp.project_server",
         "--project-root", str(project_root)],
        input=payload, text=True, encoding="utf-8", capture_output=True, timeout=30, env=env,
    )
    assert proc.returncode == 0, f"MCP server rc={proc.returncode}\n{proc.stderr}"
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def _call(tool: str, args: dict, project_root: Path, msg_id: int = 2) -> dict | list:
    """Call an MCP tool and return parsed result.

    If the response has multiple content blocks (e.g. list_components returns one per
    component), returns a list of parsed dicts. Otherwise returns the single parsed dict.
    """
    responses = _mcp(
        {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
         "params": {"name": tool, "arguments": args}},
        project_root=project_root,
    )
    resp = next(r for r in responses if r.get("id") == msg_id)
    assert "error" not in resp, f"tool {tool!r} error: {resp['error']}"
    blocks = resp["result"]["content"]
    parsed = [json.loads(b["text"]) for b in blocks]
    return parsed if len(parsed) > 1 else parsed[0]


# ── tools/list ────────────────────────────────────────────────────────────────

def test_mcp_exposes_component_tools(tmp_path):
    responses = _mcp(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        project_root=tmp_path,
    )
    resp = next(r for r in responses if r.get("id") == 2)
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "list_components" in names
    assert "install_component_tool" in names
    assert "enable_component_tool" in names
    assert "disable_component_tool" in names
    assert "project_status" in names
    assert "read_project_file" in names


# ── list_components ───────────────────────────────────────────────────────────

def test_mcp_list_components_returns_all(tmp_path):
    result = _call("list_components", {}, project_root=tmp_path)
    components = result if isinstance(result, list) else [result]
    ids = {c.get("component_id", c.get("name", "")) for c in components}
    assert "core-lifecycle" in ids
    assert len(ids) >= 7


def test_mcp_list_shows_not_installed_for_fresh_dir(tmp_path):
    result = _call("list_components", {}, project_root=tmp_path)
    components = result if isinstance(result, list) else [result]
    for c in components:
        assert c.get("status") == "not-installed", f"unexpected state: {c}"


# ── project_status ────────────────────────────────────────────────────────────

def test_mcp_project_status_on_fresh_dir(tmp_path):
    result = _call("project_status", {}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert "install_state" in payload
    assert payload["install_state"] in ("installed", "not-installed", "none", "invalid")


def test_mcp_project_status_after_install(tmp_path):
    _call("install_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    result = _call("project_status", {}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["install_state"] == "installed"
    assert "core-lifecycle" in payload["components"]
    assert payload["components"]["core-lifecycle"]["status"] == "installed"


# ── install / disable / enable via MCP ───────────────────────────────────────

def test_mcp_install_component(tmp_path):
    result = _call("install_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["ok"] is True
    assert payload["component_id"] == "core-lifecycle"
    marker = tmp_path / ".audiagentic" / "components" / "core-lifecycle.yaml"
    assert marker.exists()


def test_mcp_disable_component(tmp_path):
    _call("install_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    result = _call("disable_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["ok"] is True
    assert payload["enabled"] is False


def test_mcp_enable_component(tmp_path):
    _call("install_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    _call("disable_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    result = _call("enable_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["ok"] is True
    assert payload["enabled"] is True


# ── read_project_file ─────────────────────────────────────────────────────────

def test_mcp_read_project_file_after_install(tmp_path):
    _call("install_component_tool", {"component_id": "core-lifecycle"}, project_root=tmp_path)
    result = _call(
        "read_project_file",
        {"relative_path": ".audiagentic/config/project.yaml"},
        project_root=tmp_path,
    )
    payload = result if isinstance(result, dict) else result[0]
    content = payload.get("content", "")
    assert len(content) > 0
