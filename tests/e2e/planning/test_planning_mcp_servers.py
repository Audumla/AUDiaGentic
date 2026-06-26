"""E2E: planning MCP servers via JSON-RPC subprocess.

Verifies both MCP servers (ag-planning-mgmt, ag-planning) start, expose the
declared tools, and return correct results.  Does not require Docker — each
server is spawned in-process via subprocess against a tmp_path project root.

For harness-config tests (verifying ag-planning-mgmt appears in the pi
agent's mcp.json after install), see the mutates_host tests at the bottom.
Those require AUDIAGENTIC_DOCKER_TESTS=1 and AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1.
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


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _read_json_line(proc: subprocess.Popen, deadline: float) -> dict | None:
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return None
            continue
        try:
            return json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _send_and_wait(
    proc: subprocess.Popen,
    messages: list[dict],
    expected_ids: set[int],
    deadline: float,
) -> list[dict]:
    assert proc.stdin is not None
    for msg in messages:
        proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()

    responses: list[dict] = []
    while time.time() < deadline:
        resp = _read_json_line(proc, deadline)
        if resp is None:
            break
        responses.append(resp)
        if expected_ids and expected_ids.issubset({r.get("id") for r in responses}):
            break
    return responses


def _terminate(proc: subprocess.Popen) -> None:
    assert proc.stdin is not None
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=5)


def _start_server(module: str, project_root: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["AUDIAGENTIC_REPO_ROOT"] = str(project_root)
    env["PYTHONPATH"] = os.pathsep.join([str(_ROOT / "src"), env.get("PYTHONPATH", "")])
    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(_INIT) + "\n")
    proc.stdin.flush()
    init_resp = _read_json_line(proc, time.time() + 10)
    assert init_resp is not None, f"MCP server {module} did not respond to initialize"
    proc.stdin.write(json.dumps(_INITIALIZED) + "\n")
    proc.stdin.flush()
    return proc


def _tools_list(proc: subprocess.Popen) -> set[str]:
    responses = _send_and_wait(
        proc,
        [{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}],
        {2},
        time.time() + 5,
    )
    resp = next((r for r in responses if r.get("id") == 2), None)
    assert resp is not None, "no tools/list response"
    return {t["name"] for t in resp["result"]["tools"]}


def _call(
    proc: subprocess.Popen,
    tool: str,
    args: dict,
    msg_id: int = 3,
) -> dict:
    responses = _send_and_wait(
        proc,
        [{"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
          "params": {"name": tool, "arguments": args}}],
        {msg_id},
        time.time() + 10,
    )
    resp = next((r for r in responses if r.get("id") == msg_id), None)
    assert resp is not None, f"no response for {tool!r}"
    assert "error" not in resp, f"tool {tool!r} returned error: {resp.get('error')}"
    blocks = resp["result"]["content"]
    parsed = [json.loads(b["text"]) for b in blocks]
    return parsed[0] if len(parsed) == 1 else parsed


# ---------------------------------------------------------------------------
# ag-planning-mgmt server
# ---------------------------------------------------------------------------

class TestPlanningMgmtMcpServer:
    """ag-planning-mgmt: management tools respond correctly."""

    def test_mgmt_server_exposes_declared_tools(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_manage_mcp", tmp_path)
        try:
            names = _tools_list(proc)
            assert {"planning_status", "planning_list_implementations", "planning_select_implementation"}.issubset(names), (
                f"Expected mgmt tools not found. Got: {names}"
            )
        finally:
            _terminate(proc)

    def test_mgmt_planning_status_returns_structure(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_manage_mcp", tmp_path)
        try:
            result = _call(proc, "planning_status", {})
            assert isinstance(result, dict), f"Expected dict, got: {result}"
            assert "implementation" in result or "active_implementation" in result, (
                f"Unexpected planning_status response: {result}"
            )
        finally:
            _terminate(proc)

    def test_mgmt_list_implementations_includes_local_docs(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_manage_mcp", tmp_path)
        try:
            result = _call(proc, "planning_list_implementations", {})
            impl_ids = (
                list(result.get("implementations", {}).keys())
                if isinstance(result, dict)
                else []
            )
            assert "planning-local-docs" in impl_ids, (
                f"planning-local-docs not in implementations: {result}"
            )
        finally:
            _terminate(proc)

    def test_mgmt_select_implementation_accepts_local_docs(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_manage_mcp", tmp_path)
        try:
            result = _call(proc, "planning_select_implementation", {"implementation": "planning-local-docs"})
            assert result.get("ok") is True, f"select_implementation failed: {result}"
        finally:
            _terminate(proc)


# ---------------------------------------------------------------------------
# ag-planning server
# ---------------------------------------------------------------------------

class TestPlanningMcpServer:
    """ag-planning: plan item tools respond correctly end-to-end."""

    def test_planning_server_exposes_declared_tools(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_mcp", tmp_path)
        try:
            names = _tools_list(proc)
            expected = {
                "plan_create_item", "plan_list_items", "plan_get_item",
                "plan_set_state", "plan_update_item", "plan_delete_item",
            }
            assert expected.issubset(names), f"Missing planning tools. Got: {names}"
        finally:
            _terminate(proc)

    def test_plan_list_items_returns_empty_on_fresh_root(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_mcp", tmp_path)
        try:
            result = _call(proc, "plan_list_items", {})
            assert result == [] or (isinstance(result, dict) and result.get("items") == []), (
                f"Expected empty list, got: {result}"
            )
        finally:
            _terminate(proc)

    def test_plan_create_then_list_roundtrip(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_mcp", tmp_path)
        try:
            item = {"id": "E2E01", "plan": "e2e-test", "title": "E2E test item"}
            create_result = _call(proc, "plan_create_item", {"item": item})
            assert create_result.get("id") == "E2E01", f"create_item failed: {create_result}"

            raw = _call(proc, "plan_list_items", {}, msg_id=4)
            # MCP emits one block per list element; a 1-item list comes back as a dict
            items = [raw] if isinstance(raw, dict) else (raw or [])
            ids = [i["id"] for i in items]
            assert "E2E01" in ids, f"E2E01 not in list after create: {items}"
        finally:
            _terminate(proc)

    def test_plan_set_state_completes_item(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_mcp", tmp_path)
        try:
            _call(proc, "plan_create_item", {"item": {"id": "E2E02", "plan": "e2e-test", "title": "Complete me"}})
            result = _call(proc, "plan_set_state", {"item_id": "E2E02", "new_state": "completed"}, msg_id=4)
            assert result.get("ok") is True
            assert result.get("state") == "completed"

            raw = _call(proc, "plan_list_items", {"state": "completed"}, msg_id=5)
            completed = [raw] if isinstance(raw, dict) else (raw or [])
            ids = [i["id"] for i in completed]
            assert "E2E02" in ids, f"E2E02 not in completed list: {completed}"
        finally:
            _terminate(proc)

    def test_plan_delete_item_removes_item(self, tmp_path: Path) -> None:
        proc = _start_server("audiagentic.components.planning.planning_mcp", tmp_path)
        try:
            _call(proc, "plan_create_item", {"item": {"id": "E2E03", "plan": "e2e-test", "title": "Delete me"}})
            del_result = _call(proc, "plan_delete_item", {"item_id": "E2E03"}, msg_id=4)
            assert del_result.get("ok") is True

            raw = _call(proc, "plan_list_items", {}, msg_id=5)
            items = [raw] if isinstance(raw, dict) else (raw or [])
            ids = [i["id"] for i in items]
            assert "E2E03" not in ids, f"E2E03 still present after delete: {items}"
        finally:
            _terminate(proc)


# ---------------------------------------------------------------------------
# Harness MCP server collection — verifies what goes into harness mcp.json
# ---------------------------------------------------------------------------

class TestPlanningHarnessMcpCollection:
    """Verify collect_mcp_servers — the source of harness mcp.json — includes planning servers.

    These tests exercise the full collection path (not a subprocess call) and
    cover what both ag-planning-mgmt and ag-planning would look like in the
    generated mcp.json without requiring a real harness installation.
    """

    def test_collect_mcp_includes_both_planning_servers_when_installed(self, tmp_path: Path) -> None:
        from audiagentic.foundation.components.loader import register_all_components
        from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers
        from audiagentic.runtime.lifecycle.components import install_component

        register_all_components()
        install_component("agent-planning", tmp_path)

        servers = collect_mcp_servers(tmp_path)
        assert "ag-planning-mgmt" in servers, (
            f"ag-planning-mgmt missing from harness mcp collection after install. "
            f"Present: {set(servers)}"
        )
        assert "ag-planning" in servers, (
            f"ag-planning missing from harness mcp collection after install. "
            f"Present: {set(servers)}"
        )

    def test_collect_mcp_excludes_planning_servers_when_not_installed(self, tmp_path: Path) -> None:
        from audiagentic.foundation.components.loader import register_all_components
        from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers

        register_all_components()
        servers = collect_mcp_servers(tmp_path)
        assert "ag-planning-mgmt" not in servers, (
            "ag-planning-mgmt should not be collected when agent-planning is not installed"
        )
        assert "ag-planning" not in servers, (
            "ag-planning should not be collected when agent-planning is not installed"
        )

    def test_collect_mcp_excludes_planning_servers_when_disabled(self, tmp_path: Path) -> None:
        from audiagentic.foundation.components.loader import register_all_components
        from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers
        from audiagentic.runtime.lifecycle.components import disable_component, install_component

        register_all_components()
        install_component("agent-planning", tmp_path)
        disable_component("agent-planning", tmp_path)

        servers = collect_mcp_servers(tmp_path)
        assert "ag-planning-mgmt" not in servers, (
            "ag-planning-mgmt should not be collected when agent-planning is disabled"
        )
        assert "ag-planning" not in servers, (
            "ag-planning should not be collected when agent-planning is disabled"
        )

    def test_planning_servers_have_correct_entry_structure(self, tmp_path: Path) -> None:
        from audiagentic.foundation.components.loader import register_all_components
        from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers
        from audiagentic.runtime.lifecycle.components import install_component

        register_all_components()
        install_component("agent-planning", tmp_path)

        servers = collect_mcp_servers(tmp_path)
        for name in ("ag-planning-mgmt", "ag-planning"):
            entry = servers[name]
            assert entry.command, f"{name}: command is empty"
            assert entry.args, f"{name}: args is empty"

    def test_pi_mcp_dict_includes_planning_servers_when_installed(self, tmp_path: Path) -> None:
        """Full pi mcp.json build path: collect → build_pi_mcp_dict → verify keys."""
        from audiagentic.foundation.components.loader import register_all_components
        from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers
        from audiagentic.runtime.harness.pi.mcp_format import build_pi_mcp_dict
        from audiagentic.runtime.lifecycle.components import install_component

        register_all_components()
        install_component("agent-planning", tmp_path)

        entries = collect_mcp_servers(tmp_path)
        pi_config = build_pi_mcp_dict(entries)

        servers = pi_config.get("mcpServers", {})
        assert "ag-planning-mgmt" in servers, (
            f"ag-planning-mgmt missing from pi mcp dict. Present: {set(servers)}"
        )
        assert "ag-planning" in servers, (
            f"ag-planning missing from pi mcp dict. Present: {set(servers)}"
        )
