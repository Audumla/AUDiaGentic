"""Full surface MCP tool call tests for audiagentic-planning server.

Tests every @mcp.tool endpoint via raw JSON-RPC stdio exchange.

Read-only tools are exercised against the real repo (safe).
Mutation tools use an isolated tmp project seeded as cwd for the subprocess.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "tools" / "mcp" / "audiagentic-planning" / "audiagentic-planning_mcp.py"
PLANNING_CONFIG_SRC = ROOT / ".audiagentic" / "planning" / "config"

for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Raw MCP helpers
# ---------------------------------------------------------------------------

_INIT_MSG = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test-harness", "version": "0.1"},
    },
}
_INITIALIZED_MSG = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {},
}

_MUTATION_TIMEOUT = 30  # seconds — absorbs Windows FS latency in full-suite runs


def _exchange(
    *messages: dict, cwd: Path | None = None, timeout: int = 10
) -> tuple[list[dict], str]:
    """Send messages to MCP server stdio, return (responses, stderr)."""
    payload = "\n".join(json.dumps(m) for m in messages) + "\n"
    env = None
    if cwd is not None:
        env = dict(**__import__("os").environ)
        env["AUDIAGENTIC_ROOT"] = str(cwd)
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=payload,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=str(cwd or ROOT),
        env=env,
        timeout=timeout,
        check=False,
    )
    stdout = proc.stdout or ""
    assert proc.returncode == 0, (
        f"MCP server exited with {proc.returncode}:\n{proc.stderr}"
    )
    responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    return responses, proc.stderr or ""


def _call_tool(
    tool_name: str, arguments: dict | None = None, cwd: Path | None = None,
    timeout: int = 10,
) -> Any:
    """Call a single MCP tool and return its decoded result."""
    call_msg = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}},
    }
    responses, _ = _exchange(_INIT_MSG, _INITIALIZED_MSG, call_msg, cwd=cwd, timeout=timeout)
    call_resp = next((r for r in responses if r.get("id") == 2), None)
    assert call_resp is not None, f"No response for tools/call to {tool_name}"
    if "error" in call_resp:
        raise RuntimeError(f"JSON-RPC error calling {tool_name}: {call_resp['error']}")
    result = call_resp["result"]
    if result.get("isError"):
        content_text = result.get("content", [{}])[0].get("text", "")
        raise RuntimeError(f"Tool {tool_name} returned isError=true: {content_text}")
    blocks = result.get("content", [])
    parsed = []
    for block in blocks:
        text = block.get("text", "")
        try:
            parsed.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            parsed.append(text)
    if len(parsed) == 1 and isinstance(parsed[0], dict) and "_result" in parsed[0]:
        return parsed[0]["_result"]
    if len(parsed) == 0:
        return None
    if len(parsed) > 1:
        return parsed
    return parsed[0]


def _call_tool_raw(
    tool_name: str, arguments: dict | None = None, cwd: Path | None = None,
    timeout: int = 10,
) -> dict:
    """Call a tool and return the raw JSON-RPC response (may contain error)."""
    call_msg = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}},
    }
    responses, _ = _exchange(_INIT_MSG, _INITIALIZED_MSG, call_msg, cwd=cwd, timeout=timeout)
    return next((r for r in responses if r.get("id") == 2), {})


def _mcall(
    tool_name: str, arguments: dict | None = None, cwd: Path | None = None
) -> Any:
    """_call_tool with mutation timeout — use for all isolated mutation tests."""
    return _call_tool(tool_name, arguments, cwd=cwd, timeout=_MUTATION_TIMEOUT)


def _mcall_raw(
    tool_name: str, arguments: dict | None = None, cwd: Path | None = None
) -> dict:
    """_call_tool_raw with mutation timeout."""
    return _call_tool_raw(tool_name, arguments, cwd=cwd, timeout=_MUTATION_TIMEOUT)


# ---------------------------------------------------------------------------
# Isolation fixture for mutation tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_project(tmp_path: Path) -> Path:
    """Seed a minimal planning project that the MCP server subprocess will find."""
    config_dir = tmp_path / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, config_dir / f.name)
    pp_src = PLANNING_CONFIG_SRC / "profile-packs"
    if pp_src.exists():
        shutil.copytree(pp_src, config_dir / "profile-packs")
    for sub in ("ids", "indexes", "events", "claims", "meta", "extracts"):
        (tmp_path / ".audiagentic" / "planning" / sub).mkdir(parents=True, exist_ok=True)
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
    ):
        (tmp_path / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Protocol and tool discovery
# ---------------------------------------------------------------------------

class TestMCPProtocol:
    def test_all_13_tools_exposed(self):
        """Every @mcp.tool in audiagentic-planning_mcp.py must be listed."""
        responses, _ = _exchange(
            _INIT_MSG,
            _INITIALIZED_MSG,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_resp = next(r for r in responses if r.get("id") == 2)
        tool_names = {t["name"] for t in tools_resp["result"]["tools"]}

        expected = {
            "tm_edit",
            "tm_create",
            "tm_get",
            "tm_list",
            "tm_section",
            "tm_move",
            "tm_delete",
            "tm_relink",
            "tm_package",
            "tm_standards",
            "tm_claim",
            "tm_docs",
            "tm_admin",
        }
        missing = expected - tool_names
        assert not missing, f"Missing MCP tools: {sorted(missing)}"
        extra = tool_names - expected
        assert not extra, f"Unexpected extra tools (update test if intentional): {sorted(extra)}"

    def test_each_tool_has_description(self):
        responses, _ = _exchange(
            _INIT_MSG,
            _INITIALIZED_MSG,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_resp = next(r for r in responses if r.get("id") == 2)
        for tool in tools_resp["result"]["tools"]:
            assert tool.get("description"), f"Tool {tool['name']} has no description"

    def test_each_tool_has_input_schema(self):
        responses, _ = _exchange(
            _INIT_MSG,
            _INITIALIZED_MSG,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_resp = next(r for r in responses if r.get("id") == 2)
        for tool in tools_resp["result"]["tools"]:
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"

    def test_unknown_tool_returns_error(self):
        resp = _call_tool_raw("tm_nonexistent_tool", {})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_missing_required_arg_returns_error(self):
        resp = _call_tool_raw("tm_create", {})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_invalid_kind_returns_error(self):
        resp = _call_tool_raw("tm_create", {"kind": "bogus", "label": "L", "summary": "S"})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_invalid_op_returns_error(self):
        resp = _call_tool_raw("tm_admin", {"op": "bogus"})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error


# ---------------------------------------------------------------------------
# 2. Read-only tools against real repo
# ---------------------------------------------------------------------------

class TestReadOnlyTools:
    def test_tm_list_mode_count(self):
        result = _call_tool("tm_list", {"mode": "count"})
        assert isinstance(result, dict)
        for kind in ("request", "spec", "plan", "task", "wp"):
            assert kind in result, f"tm_list count missing key: {kind}"

    def test_tm_list_mode_list(self):
        result = _call_tool("tm_list")
        assert isinstance(result, list)

    def test_tm_list_filtered_by_kind(self):
        result = _call_tool("tm_list", {"kind": "request"})
        assert isinstance(result, list)
        assert all(i.get("kind") == "request" for i in result if "kind" in i)

    def test_tm_list_filtered_by_state(self):
        result = _call_tool("tm_list", {"kind": "request", "state": "distilled"})
        assert isinstance(result, list)
        assert all(i.get("state") == "distilled" for i in result)

    def test_tm_list_mode_next(self):
        result = _call_tool("tm_list", {"kind": "task", "mode": "next"})
        assert isinstance(result, list)

    def test_tm_list_include_deleted(self):
        result = _call_tool("tm_list", {"include_deleted": True})
        assert isinstance(result, list)

    def test_tm_get_depth_head(self):
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests in real repo")
        result = _call_tool("tm_get", {"id": items[0]["id"], "depth": "head"})
        assert "id" in result
        assert "kind" in result
        assert "path" in result
        assert "body" not in result

    def test_tm_get_depth_meta(self):
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests in real repo")
        result = _call_tool("tm_get", {"id": items[0]["id"], "depth": "meta"})
        assert result["id"] == items[0]["id"]
        assert "kind" in result
        assert "state" in result

    def test_tm_get_depth_full(self):
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests in real repo")
        result = _call_tool("tm_get", {"id": items[0]["id"], "depth": "full"})
        assert "item" in result
        assert "body" in result

    def test_tm_get_depth_body(self):
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests in real repo")
        result = _call_tool("tm_get", {"id": items[0]["id"], "depth": "body"})
        assert isinstance(result, str)

    def test_tm_get_with_related(self):
        items = _call_tool("tm_list", {"kind": "spec"})
        if not items:
            pytest.skip("No specs in real repo")
        result = _call_tool("tm_get", {"id": items[0]["id"], "depth": "full", "with_related": True})
        assert "related" in result

    def test_tm_get_unknown_item_returns_error(self):
        resp = _call_tool_raw("tm_get", {"id": "request-99999"})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_tm_section_get(self):
        items = _call_tool("tm_list", {"kind": "task"})
        if not items:
            pytest.skip("No tasks in real repo")
        result = _call_tool("tm_section", {"id": items[0]["id"], "op": "get", "section": "Description"})
        assert isinstance(result, dict)
        assert "found" in result

    def test_tm_section_get_sub(self):
        items = _call_tool("tm_list", {"kind": "task"})
        if not items:
            pytest.skip("No tasks in real repo")
        result = _call_tool("tm_section", {"id": items[0]["id"], "op": "get_sub", "section": "description"})
        assert isinstance(result, dict)
        assert "found" in result

    def test_tm_admin_validate(self):
        result = _call_tool("tm_admin", {"op": "validate"})
        assert isinstance(result, list)
        assert all(isinstance(e, str) for e in result)

    def test_tm_admin_verify(self):
        result = _call_tool("tm_admin", {"op": "verify"})
        assert isinstance(result, dict)
        assert "healthy" in result
        assert "checks" in result
        assert "summary" in result

    def test_tm_admin_events(self):
        result = _call_tool("tm_admin", {"op": "events", "tail": 10})
        assert isinstance(result, list)
        assert len(result) <= 10

    def test_tm_admin_events_default_tail(self):
        result = _call_tool("tm_admin", {"op": "events"})
        assert isinstance(result, list)
        assert len(result) <= 20

    def test_tm_claim_list(self):
        result = _call_tool("tm_claim", {"op": "list"})
        assert isinstance(result, list)

    def test_tm_claim_list_filtered_by_kind(self):
        result = _call_tool("tm_claim", {"op": "list", "kind": "task"})
        assert isinstance(result, list)
        assert all(c.get("kind") == "task" for c in result)

    def test_tm_standards_list_all(self):
        result = _call_tool("tm_standards")
        assert isinstance(result, list)

    def test_tm_standards_get_standard(self):
        stds = _call_tool("tm_standards")
        if not stds:
            pytest.skip("No standards in real repo")
        std_id = stds[0]["id"]
        result = _call_tool("tm_standards", {"id": std_id})
        assert "item" in result
        assert "body" in result

    def test_tm_standards_applicable_for_item(self):
        items = _call_tool("tm_list", {"kind": "task"})
        if not items:
            pytest.skip("No tasks in real repo")
        result = _call_tool("tm_standards", {"id": items[0]["id"]})
        assert isinstance(result, list)

    def test_tm_docs_surfaces(self):
        result = _call_tool("tm_docs", {"op": "surfaces"})
        assert isinstance(result, list)
        assert len(result) > 0

    def test_tm_docs_surface(self):
        result = _call_tool("tm_docs", {"op": "surface", "id": "readme"})
        assert result is not None
        assert result.get("id") == "readme"

    def test_tm_docs_surface_unknown(self):
        resp = _call_tool_raw("tm_docs", {"op": "surface", "id": "nonexistent-surface"})
        result = resp.get("result", {})
        content_text = result.get("content", [{}])[0].get("text", "null")
        if '"_result": null' in content_text or '"_result": None' in content_text:
            content_text = "null"
        assert content_text in ("null", "None", "") or "error" in resp

    def test_tm_docs_profiles(self):
        result = _call_tool("tm_docs", {"op": "profiles"})
        assert isinstance(result, list)
        assert len(result) > 0

    def test_tm_docs_profile(self):
        result = _call_tool("tm_docs", {"op": "profile", "id": "feature"})
        assert result is not None
        assert result.get("id") == "feature"

    def test_tm_docs_refs(self):
        result = _call_tool("tm_docs", {"op": "refs"})
        assert isinstance(result, list)

    def test_tm_docs_support(self):
        result = _call_tool("tm_docs", {"op": "support"})
        assert isinstance(result, list)

    def test_tm_docs_sync_req(self):
        result = _call_tool("tm_docs", {"op": "sync_req", "kind": "task"})
        assert isinstance(result, dict)
        assert "required_updates" in result

    def test_tm_docs_pending(self):
        result = _call_tool("tm_docs", {"op": "pending", "kind": "task"})
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 3. Mutation tools — require isolated project
# ---------------------------------------------------------------------------

class TestMCPMutationIsolated:
    """Mutation tests that require a fully isolated MCP project.

    All tool calls use _mcall/_mcall_raw (30s timeout) to absorb Windows FS
    latency when the full suite runs.
    """

    def test_tm_create_request(self, isolated_project):
        result = _mcall(
            "tm_create",
            {"kind": "request", "label": "MCP Test Request", "summary": "Created by test", "source": "test"},
            cwd=isolated_project,
        )
        assert "id" in result
        assert result["id"].startswith("request-")

    def test_tm_create_request_persists_source_and_context(self, isolated_project):
        _mcall(
            "tm_create",
            {"kind": "request", "label": "Traceable", "summary": "S", "source": "mcp", "context": "integration test"},
            cwd=isolated_project,
        )
        shown = _mcall("tm_get", {"id": "request-0001", "depth": "meta"}, cwd=isolated_project)
        assert shown["source"] == "mcp"
        assert shown["context"] == "integration test"

    def test_tm_create_spec(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall(
            "tm_create",
            {"kind": "spec", "label": "Isolated Spec", "summary": "MCP spec test", "request_refs": ["request-0001"]},
            cwd=isolated_project,
        )
        assert result["id"].startswith("spec-")

    def test_tm_create_spec_requires_request_refs(self, isolated_project):
        resp = _mcall_raw(
            "tm_create",
            {"kind": "spec", "label": "Orphan Spec", "summary": "Should fail"},
            cwd=isolated_project,
        )
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error, "Expected error when creating spec without request_refs"

    def test_tm_create_plan(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        result = _mcall(
            "tm_create",
            {"kind": "plan", "label": "Isolated Plan", "summary": "MCP plan test", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("plan-")

    def test_tm_create_task(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        result = _mcall(
            "tm_create",
            {"kind": "task", "label": "Isolated Task", "summary": "MCP task test", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("task-")

    def test_tm_create_task_missing_spec_returns_error(self, isolated_project):
        resp = _mcall_raw("tm_create", {"kind": "task", "label": "T", "summary": "S"}, cwd=isolated_project)
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_tm_create_wp(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "plan", "label": "PL", "summary": "P", "spec": "spec-0001"}, cwd=isolated_project)
        result = _mcall(
            "tm_create",
            {"kind": "wp", "label": "Isolated WP", "summary": "MCP wp test", "plan": "plan-0001"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("wp-")

    def test_tm_create_standard(self, isolated_project):
        result = _mcall(
            "tm_create",
            {"kind": "standard", "label": "Isolated Standard", "summary": "MCP standard test"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("standard-")

    def test_tm_create_with_content(self, isolated_project):
        result = _mcall(
            "tm_create",
            {
                "kind": "request",
                "label": "Rich Request",
                "summary": "Has content",
                "content": "# Problem\n\nThe problem.\n\n# Desired Outcome\n\nBetter state.\n",
                "source": "test",
            },
            cwd=isolated_project,
        )
        assert result["id"].startswith("request-")
        body = _mcall("tm_get", {"id": result["id"], "depth": "body"}, cwd=isolated_project)
        assert "The problem." in body

    def test_tm_create_duplicate_detection(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "Dup Label", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_create", {"kind": "request", "label": "Dup Label", "summary": "S", "source": "test"}, cwd=isolated_project)
        assert result.get("created") is False
        assert "duplicate_of" in result

    def test_tm_get_all_depths(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        head = _mcall("tm_get", {"id": "request-0001", "depth": "head"}, cwd=isolated_project)
        assert "path" in head
        assert "body" not in head
        meta = _mcall("tm_get", {"id": "request-0001", "depth": "meta"}, cwd=isolated_project)
        assert "state" in meta
        full = _mcall("tm_get", {"id": "request-0001", "depth": "full"}, cwd=isolated_project)
        assert "item" in full
        assert "body" in full
        body = _mcall("tm_get", {"id": "request-0001", "depth": "body"}, cwd=isolated_project)
        assert isinstance(body, str)

    def test_tm_get_unknown_returns_error(self, isolated_project):
        resp = _mcall_raw("tm_get", {"id": "request-99999"}, cwd=isolated_project)
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_tm_list_mode_list(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R1", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "request", "label": "R2", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_list", {"kind": "request"}, cwd=isolated_project)
        assert len(result) >= 2

    def test_tm_list_mode_count(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_list", {"mode": "count"}, cwd=isolated_project)
        assert isinstance(result, dict)
        assert result.get("request", {}).get("captured", 0) >= 1

    def test_tm_list_mode_next(self, isolated_project):
        result = _mcall("tm_list", {"kind": "task", "mode": "next"}, cwd=isolated_project)
        assert isinstance(result, list)

    def test_tm_list_state_filter(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_list", {"kind": "request", "state": "captured"}, cwd=isolated_project)
        assert isinstance(result, list)
        assert all(i.get("state") == "captured" for i in result)

    def test_tm_edit_single_op(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        result = _mcall(
            "tm_edit",
            {"id": "spec-0001", "operations": [{"op": "state", "value": "ready"}]},
            cwd=isolated_project,
        )
        assert "results" in result

    def test_tm_edit_multi_op(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "task", "label": "T", "summary": "Old", "spec": "spec-0001"}, cwd=isolated_project)
        _mcall("tm_edit", {"id": "task-0001", "operations": [{"op": "state", "value": "ready"}]}, cwd=isolated_project)
        result = _mcall(
            "tm_edit",
            {
                "id": "task-0001",
                "operations": [
                    {"op": "state", "value": "in_progress"},
                    {"op": "summary", "value": "New summary"},
                    {"op": "section", "name": "Notes", "content": "Started.", "mode": "set"},
                ],
            },
            cwd=isolated_project,
        )
        assert "results" in result

    def test_tm_edit_invalid_transition_returns_error(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        # _execute_batch_operations catches exceptions and returns {success: False} rather than
        # raising — FastMCP returns this as a normal response, not isError=true.
        result = _mcall(
            "tm_edit",
            {"id": "spec-0001", "operations": [{"op": "state", "value": "done"}]},
            cwd=isolated_project,
        )
        assert result.get("success") is False, (
            f"Expected batch failure for invalid state transition (draft→done), got: {result}"
        )

    def test_tm_edit_content_replace(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall(
            "tm_edit",
            {"id": "request-0001", "operations": [{"op": "content", "value": "# Notes\n\nReplaced.\n", "mode": "replace"}]},
            cwd=isolated_project,
        )
        body = _mcall("tm_get", {"id": "request-0001", "depth": "body"}, cwd=isolated_project)
        assert "Replaced." in body

    def test_tm_edit_label_and_summary(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "Original", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall(
            "tm_edit",
            {"id": "request-0001", "operations": [{"op": "label", "value": "Updated"}, {"op": "summary", "value": "New summary"}]},
            cwd=isolated_project,
        )
        assert "results" in result

    def test_tm_section_set_and_get(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        _mcall(
            "tm_edit",
            {"id": "spec-0001", "operations": [{"op": "content", "value": "# Purpose\n\nOld.\n\n# Scope\n\nScope.\n", "mode": "replace"}]},
            cwd=isolated_project,
        )
        _mcall("tm_section", {"id": "spec-0001", "op": "set", "section": "Purpose", "content": "New purpose."}, cwd=isolated_project)
        body = _mcall("tm_get", {"id": "spec-0001", "depth": "body"}, cwd=isolated_project)
        assert "New purpose." in body

    def test_tm_section_append(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        _mcall(
            "tm_edit",
            {"id": "spec-0001", "operations": [{"op": "content", "value": "# Notes\n\nBase.\n", "mode": "replace"}]},
            cwd=isolated_project,
        )
        _mcall("tm_section", {"id": "spec-0001", "op": "append", "section": "Notes", "content": "Appended note."}, cwd=isolated_project)
        body = _mcall("tm_get", {"id": "spec-0001", "depth": "body"}, cwd=isolated_project)
        assert "Appended note." in body

    def test_tm_section_set_requires_content(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        resp = _mcall_raw("tm_section", {"id": "request-0001", "op": "set", "section": "Notes"}, cwd=isolated_project)
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_tm_move_task(self, isolated_project):
        (isolated_project / "docs" / "planning" / "tasks" / "contrib").mkdir(parents=True, exist_ok=True)
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "task", "label": "T", "summary": "S", "spec": "spec-0001"}, cwd=isolated_project)
        result = _mcall("tm_move", {"id": "task-0001", "domain": "contrib"}, cwd=isolated_project)
        assert "contrib" in result.get("path", "")

    def test_tm_delete_soft(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "ToDelete", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_delete", {"id": "request-0001", "reason": "test cleanup"}, cwd=isolated_project)
        assert result["hard_delete"] is False

    def test_tm_delete_hard(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "ToHardDelete", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_delete", {"id": "request-0001", "hard": True, "reason": "test"}, cwd=isolated_project)
        assert result["hard_delete"] is True

    def test_tm_relink(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        result = _mcall(
            "tm_relink",
            {"src": "spec-0001", "field": "request_refs", "dst": "request-0001"},
            cwd=isolated_project,
        )
        assert "id" in result

    def test_tm_package(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "plan", "label": "PL", "summary": "P", "spec": "spec-0001"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "task", "label": "T1", "summary": "S", "spec": "spec-0001"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "task", "label": "T2", "summary": "S", "spec": "spec-0001"}, cwd=isolated_project)
        result = _mcall(
            "tm_package",
            {"plan": "plan-0001", "tasks": ["task-0001", "task-0002"], "label": "WP", "summary": "S"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("wp-")

    def test_tm_standards_list_all(self, isolated_project):
        _mcall("tm_create", {"kind": "standard", "label": "Code Style", "summary": "Use consistent formatting"}, cwd=isolated_project)
        result = _mcall("tm_standards", cwd=isolated_project)
        assert isinstance(result, list)
        assert any(s["id"] == "standard-0001" for s in result)

    def test_tm_standards_get_one(self, isolated_project):
        _mcall("tm_create", {"kind": "standard", "label": "Code Style", "summary": "S"}, cwd=isolated_project)
        result = _mcall("tm_standards", {"id": "standard-0001"}, cwd=isolated_project)
        assert "item" in result
        assert result["item"]["kind"] == "standard"

    def test_tm_standards_applicable_for_item(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "task", "label": "T", "summary": "S", "spec": "spec-0001"}, cwd=isolated_project)
        result = _mcall("tm_standards", {"id": "task-0001"}, cwd=isolated_project)
        assert isinstance(result, list)

    def test_tm_claim_and_unclaim(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall("tm_create", {"kind": "spec", "label": "SP", "summary": "S", "request_refs": ["request-0001"]}, cwd=isolated_project)
        claim = _mcall("tm_claim", {"op": "claim", "kind": "spec", "id": "spec-0001", "holder": "agent-test", "ttl": 300}, cwd=isolated_project)
        assert claim["holder"] == "agent-test"
        active = _mcall("tm_claim", {"op": "list", "kind": "spec"}, cwd=isolated_project)
        assert any(c["id"] == "spec-0001" for c in active)
        _mcall("tm_claim", {"op": "unclaim", "id": "spec-0001"}, cwd=isolated_project)
        after = _mcall("tm_claim", {"op": "list", "kind": "spec"}, cwd=isolated_project)
        assert not any(c["id"] == "spec-0001" for c in after)

    def test_tm_claim_missing_args_returns_error(self, isolated_project):
        resp = _mcall_raw("tm_claim", {"op": "claim", "id": "task-0001"}, cwd=isolated_project)
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_tm_admin_validate(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_admin", {"op": "validate"}, cwd=isolated_project)
        assert isinstance(result, list)

    def test_tm_admin_index(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        resp = _mcall_raw("tm_admin", {"op": "index"}, cwd=isolated_project)
        assert "error" not in resp

    def test_tm_admin_reconcile(self, isolated_project):
        result = _mcall("tm_admin", {"op": "reconcile"}, cwd=isolated_project)
        assert isinstance(result, dict)
        assert "orphans" in result

    def test_tm_admin_events(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_admin", {"op": "events", "tail": 5}, cwd=isolated_project)
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_tm_admin_verify(self, isolated_project):
        result = _mcall("tm_admin", {"op": "verify"}, cwd=isolated_project)
        assert isinstance(result, dict)
        assert "healthy" in result

    def test_tm_admin_check_sensitive_clean(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        result = _mcall("tm_admin", {"op": "check_sensitive", "id": "request-0001"}, cwd=isolated_project)
        assert isinstance(result, dict)
        assert "has_sensitive_data" in result
        assert result["has_sensitive_data"] is False

    def test_tm_admin_check_sensitive_detects_token(self, isolated_project):
        _mcall("tm_create", {"kind": "request", "label": "R", "summary": "S", "source": "test"}, cwd=isolated_project)
        _mcall(
            "tm_edit",
            {"id": "request-0001", "operations": [
                {"op": "content", "value": "# Notes\n\nAuthorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret\n", "mode": "replace"}
            ]},
            cwd=isolated_project,
        )
        result = _mcall("tm_admin", {"op": "check_sensitive", "id": "request-0001"}, cwd=isolated_project)
        assert result["has_sensitive_data"] is True

    def test_tm_admin_check_sensitive_requires_id(self, isolated_project):
        resp = _mcall_raw("tm_admin", {"op": "check_sensitive"}, cwd=isolated_project)
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_tm_docs_surfaces(self, isolated_project):
        result = _mcall("tm_docs", {"op": "surfaces"}, cwd=isolated_project)
        assert isinstance(result, list)

    def test_tm_docs_sync_req(self, isolated_project):
        result = _mcall("tm_docs", {"op": "sync_req", "kind": "task"}, cwd=isolated_project)
        assert isinstance(result, dict)

    def test_tm_docs_pending(self, isolated_project):
        result = _mcall("tm_docs", {"op": "pending", "kind": "task"}, cwd=isolated_project)
        assert isinstance(result, list)
