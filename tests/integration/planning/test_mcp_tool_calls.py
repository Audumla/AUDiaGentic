"""Full surface MCP tool call tests for audiagentic-planning server.

Tests every @mcp.tool endpoint via raw JSON-RPC stdio exchange.

Read-only tools are exercised against the real repo (safe).
Mutation tools use an isolated tmp project seeded as cwd for the subprocess.

NOTE: Mutation test isolation relies on the MCP server finding the project
root via cwd first (search_roots[0] = cwd). This works only if cwd has
.audiagentic/planning/ AND the subprocess can still resolve Python imports.
Tests that cannot achieve this are marked xfail with a note for the
implementing request.
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
    tool_name: str, arguments: dict | None = None, cwd: Path | None = None
) -> Any:
    """Call a single MCP tool and return its decoded result.

    FastMCP serializes Python lists as multiple content blocks (one per item)
    and dicts/scalars as a single block. This helper normalises both:
      - multiple blocks → list of parsed JSON values
      - single block    → parsed JSON value (dict, str, bool, None, …)

    Raises RuntimeError if the server returns a JSON-RPC error or tool isError.
    """
    call_msg = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}},
    }
    responses, _ = _exchange(_INIT_MSG, _INITIALIZED_MSG, call_msg, cwd=cwd)
    call_resp = next((r for r in responses if r.get("id") == 2), None)
    assert call_resp is not None, f"No response for tools/call to {tool_name}"
    if "error" in call_resp:
        raise RuntimeError(f"JSON-RPC error calling {tool_name}: {call_resp['error']}")
    result = call_resp["result"]
    if result.get("isError"):
        content_text = result.get("content", [{}])[0].get("text", "")
        raise RuntimeError(f"Tool {tool_name} returned isError=true: {content_text}")
    # Decode all content blocks
    blocks = result.get("content", [])
    parsed = []
    for block in blocks:
        text = block.get("text", "")
        try:
            parsed.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            parsed.append(text)
    # Handle wrapped list case: {"_result": [...]}
    if len(parsed) == 1 and isinstance(parsed[0], dict) and "_result" in parsed[0]:
        return parsed[0]["_result"]
    if len(parsed) == 0:
        return None
    # If we have multiple blocks, return as list
    if len(parsed) > 1:
        return parsed
    # If we have a single block, return it
    return parsed[0]


def _call_tool_raw(
    tool_name: str, arguments: dict | None = None, cwd: Path | None = None
) -> dict:
    """Call a tool and return the raw JSON-RPC response (may contain error)."""
    call_msg = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}},
    }
    responses, _ = _exchange(_INIT_MSG, _INITIALIZED_MSG, call_msg, cwd=cwd)
    return next((r for r in responses if r.get("id") == 2), {})


def _request_args(label: str, summary: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"label": label, "summary": summary, "source": "test"}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Isolation fixture for mutation tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_project(tmp_path: Path) -> Path:
    """Seed a minimal planning project that the MCP server subprocess will find.

    IMPORTANT: The MCP server searches for the project root starting from cwd.
    We seed .audiagentic/planning/ in tmp_path so it is found first.
    Python imports still work because the test runner's PYTHONPATH includes
    the real repo's src/.

    NOTE: tools/planning/tm_helper.py is imported by the MCP server via
    'import tools.planning.tm_helper'. This module is found on sys.path from
    the repo root (added by _bootstrap_repo_root). Until MCP root isolation
    is formally implemented (see planning request), the server will fall back
    to the real repo root for tm._ROOT if tmp_path cannot satisfy the 'tools'
    marker. These tests are therefore marked xfail where isolation is required.
    """
    config_dir = tmp_path / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, config_dir / f.name)
    pp_src = PLANNING_CONFIG_SRC / "profile-packs"
    if pp_src.exists():
        shutil.copytree(pp_src, config_dir / "profile-packs")
    for sub in ("ids", "indexes", "events", "claims", "meta", "extracts"):
        (tmp_path / ".audiagentic" / "planning" / sub).mkdir(
            parents=True, exist_ok=True
        )
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
    def test_all_46_tools_exposed(self):
        """Every @mcp.tool in audiagentic-planning_mcp.py must be listed."""
        responses, _ = _exchange(
            _INIT_MSG,
            _INITIALIZED_MSG,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_resp = next(r for r in responses if r.get("id") == 2)
        tool_names = {t["name"] for t in tools_resp["result"]["tools"]}

        expected = {
            # create
            "tm_new_request",
            "tm_new_spec",
            "tm_new_plan",
            "tm_new_task",
            "tm_new_wp",
            "tm_new_standard",
            "tm_create_with_content",
            # mutate
            "tm_update",
            "tm_batch_update",
            "tm_state",
            "tm_move",
            "tm_relink",
            "tm_package",
            "tm_delete",
            # content editing
            "tm_get_content",
            "tm_update_content",
            "tm_get_section",
            "tm_set_section",
            "tm_append_section",
            "tm_get_subsection",
            # query
            "tm_list",
            "tm_head",
            "tm_show",
            "tm_extract",
            "tm_next_tasks",
            "tm_next_items",
            "tm_status",
            # governance
            "tm_claim",
            "tm_unclaim",
            "tm_claims",
            "tm_standards",
            "tm_list_standards",
            "tm_get_standard",
            # doc surfaces
            "tm_list_doc_surfaces",
            "tm_get_doc_surface",
            "tm_list_reference_docs",
            "tm_list_request_profiles",
            "tm_get_request_profile",
            "tm_list_support_docs",
            "tm_doc_sync_requirements",
            "tm_pending_doc_updates",
            # system
            "tm_validate",
            "tm_index",
            "tm_reconcile",
            "tm_events",
            "tm_verify_structure",
        }
        missing = expected - tool_names
        assert not missing, f"Missing MCP tools: {sorted(missing)}"

    def test_each_tool_has_description(self):
        """Every tool must have a non-empty description."""
        responses, _ = _exchange(
            _INIT_MSG,
            _INITIALIZED_MSG,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_resp = next(r for r in responses if r.get("id") == 2)
        for tool in tools_resp["result"]["tools"]:
            assert tool.get("description"), f"Tool {tool['name']} has no description"

    def test_each_tool_has_input_schema(self):
        """Every tool must expose an inputSchema."""
        responses, _ = _exchange(
            _INIT_MSG,
            _INITIALIZED_MSG,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_resp = next(r for r in responses if r.get("id") == 2)
        for tool in tools_resp["result"]["tools"]:
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"

    def test_unknown_tool_returns_error(self):
        """Calling a nonexistent tool should return a JSON-RPC error or isError."""
        resp = _call_tool_raw("tm_nonexistent_tool", {})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error, f"Expected error for unknown tool, got: {resp}"

    def test_missing_required_arg_returns_error(self):
        """tm_new_request requires label and summary — omitting them should error."""
        resp = _call_tool_raw("tm_new_request", {})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error, f"Expected error for missing required args, got: {resp}"

    def test_tm_new_task_missing_spec_returns_error(self):
        """tm_new_task requires spec; omitting it should return an error."""
        resp = _call_tool_raw("tm_new_task", {"label": "T", "summary": "S"})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error, f"Expected error for missing spec, got: {resp}"


# ---------------------------------------------------------------------------
# 2. Read-only tools against real repo (always safe)
# ---------------------------------------------------------------------------


class TestReadOnlyTools:
    def test_tm_status_returns_kind_counts(self):
        result = _call_tool("tm_status")
        assert isinstance(result, dict)
        for kind in ("request", "spec", "plan", "task", "wp"):
            assert kind in result, f"tm_status missing key: {kind}"

    def test_tm_list_returns_list(self):
        result = _call_tool("tm_list")
        assert isinstance(result, list)

    def test_tm_list_filtered_by_kind(self):
        result = _call_tool("tm_list", {"kind": "request"})
        assert isinstance(result, list)
        assert all(i.get("kind") == "request" for i in result if "kind" in i)

    def test_tm_list_includes_deleted_flag(self):
        result = _call_tool("tm_list", {"include_deleted": True})
        assert isinstance(result, list)

    def test_tm_validate_returns_list_of_strings(self):
        result = _call_tool("tm_validate")
        assert isinstance(result, list)
        assert all(isinstance(e, str) for e in result)

    def test_tm_verify_structure_returns_health_dict(self):
        result = _call_tool("tm_verify_structure")
        assert isinstance(result, dict)
        assert "healthy" in result
        assert "checks" in result
        assert "summary" in result
        assert isinstance(result["healthy"], bool)

    def test_tm_events_returns_list(self):
        result = _call_tool("tm_events", {"tail": 10})
        assert isinstance(result, list)

    def test_tm_events_default_tail(self):
        result = _call_tool("tm_events")
        assert isinstance(result, list)
        assert len(result) <= 20

    def test_tm_next_tasks_returns_list(self):
        result = _call_tool("tm_next_tasks")
        assert isinstance(result, list)

    def test_tm_next_tasks_with_state(self):
        result = _call_tool("tm_next_tasks", {"state": "in_progress"})
        assert isinstance(result, list)

    def test_tm_next_items_returns_list(self):
        result = _call_tool("tm_next_items", {"kind": "task", "state": "ready"})
        assert isinstance(result, list)

    def test_tm_next_items_for_wp(self):
        result = _call_tool("tm_next_items", {"kind": "wp", "state": "ready"})
        assert isinstance(result, list)

    def test_tm_claims_returns_list(self):
        result = _call_tool("tm_claims")
        assert isinstance(result, list)

    def test_tm_claims_filtered_by_kind(self):
        result = _call_tool("tm_claims", {"kind": "task"})
        assert isinstance(result, list)
        assert all(c.get("kind") == "task" for c in result)

    def test_tm_list_standards_returns_list(self):
        result = _call_tool("tm_list_standards")
        assert isinstance(result, list)

    def test_tm_list_doc_surfaces_returns_list(self):
        result = _call_tool("tm_list_doc_surfaces")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_tm_list_doc_surfaces_each_has_id(self):
        result = _call_tool("tm_list_doc_surfaces")
        for surface in result:
            assert "id" in surface, f"Surface missing id: {surface}"

    def test_tm_get_doc_surface_readme(self):
        result = _call_tool("tm_get_doc_surface", {"surface_id": "readme"})
        assert result is not None
        assert result.get("id") == "readme"

    def test_tm_get_doc_surface_unknown_returns_none_or_error(self):
        resp = _call_tool_raw(
            "tm_get_doc_surface", {"surface_id": "nonexistent-surface"}
        )
        result = resp.get("result", {})
        content_text = result.get("content", [{}])[0].get("text", "null")
        # Should return null/None or an error — not an unhandled exception
        # Handle wrapped null case: {"_result": null}
        if '"_result": null' in content_text or '"_result": None' in content_text:
            content_text = "null"
        assert content_text in ("null", "None", "") or "error" in resp

    def test_tm_list_request_profiles_returns_list(self):
        result = _call_tool("tm_list_request_profiles")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_tm_list_request_profiles_includes_feature(self):
        result = _call_tool("tm_list_request_profiles")
        ids = {p["id"] for p in result}
        assert "feature" in ids

    def test_tm_get_request_profile_feature(self):
        result = _call_tool("tm_get_request_profile", {"profile_id": "feature"})
        assert result is not None
        assert result.get("id") == "feature"
        assert "label" in result

    def test_tm_get_request_profile_unknown_returns_none(self):
        resp = _call_tool_raw("tm_get_request_profile", {"profile_id": "nonexistent"})
        content_text = (
            resp.get("result", {}).get("content", [{}])[0].get("text", "null")
        )
        # Handle wrapped null case: {"_result": null}
        if '"_result": null' in content_text or '"_result": None' in content_text:
            content_text = "null"
        assert content_text in ("null", "None", "") or "error" in resp

    def test_tm_list_reference_docs_returns_list(self):
        result = _call_tool("tm_list_reference_docs")
        assert isinstance(result, list)

    def test_tm_list_support_docs_returns_list(self):
        result = _call_tool("tm_list_support_docs")
        assert isinstance(result, list)

    def test_tm_doc_sync_requirements_task(self):
        result = _call_tool(
            "tm_doc_sync_requirements", {"kind": "task", "profile_pack": "standard"}
        )
        assert isinstance(result, dict)
        assert "required_updates" in result

    def test_tm_doc_sync_requirements_wp(self):
        result = _call_tool(
            "tm_doc_sync_requirements", {"kind": "wp", "profile_pack": "standard"}
        )
        assert isinstance(result, dict)

    def test_tm_pending_doc_updates_task(self):
        result = _call_tool(
            "tm_pending_doc_updates", {"kind": "task", "profile_pack": "standard"}
        )
        assert isinstance(result, list)

    def test_tm_show_existing_request(self):
        """Show the first available request in the real repo."""
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests in real repo to show")
        first_id = items[0]["id"]
        result = _call_tool("tm_show", {"id": first_id})
        assert result["id"] == first_id
        assert "kind" in result
        assert "state" in result

    def test_tm_show_unknown_item_returns_error(self):
        resp = _call_tool_raw("tm_show", {"id": "request-99999"})
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error

    def test_tm_head_existing_request(self):
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests in real repo to show")
        first_id = items[0]["id"]
        result = _call_tool("tm_head", {"id": first_id})
        assert result["id"] == first_id
        assert "kind" in result
        assert "path" in result
        assert "body" not in result

    def test_tm_get_content_existing_item(self):
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests to fetch content for")
        first_id = items[0]["id"]
        result = _call_tool("tm_get_content", {"id": first_id})
        assert isinstance(result, str)

    def test_tm_extract_existing_item(self):
        items = _call_tool("tm_list", {"kind": "request"})
        if not items:
            pytest.skip("No requests to extract")
        first_id = items[0]["id"]
        result = _call_tool("tm_extract", {"id": first_id})
        assert "item" in result
        assert "body" in result
        assert "effective_standard_refs" in result

    def test_tm_extract_with_related(self):
        items = _call_tool("tm_list", {"kind": "spec"})
        if not items:
            pytest.skip("No specs in repo")
        first_id = items[0]["id"]
        result = _call_tool("tm_extract", {"id": first_id, "with_related": True})
        assert "related" in result

    def test_tm_extract_can_skip_body(self):
        items = _call_tool("tm_list", {"kind": "spec"})
        if not items:
            pytest.skip("No specs in repo")
        first_id = items[0]["id"]
        result = _call_tool(
            "tm_extract",
            {"id": first_id, "include_body": False, "write_to_disk": False},
        )
        assert "item" in result
        assert "body" not in result

    def test_tm_standards_existing_item(self):
        items = _call_tool("tm_list", {"kind": "task"})
        if not items:
            pytest.skip("No tasks in repo")
        first_id = items[0]["id"]
        result = _call_tool("tm_standards", {"id": first_id})
        assert isinstance(result, list)

    def test_tm_get_section_existing_item(self):
        items = _call_tool("tm_list", {"kind": "task"})
        if not items:
            pytest.skip("No tasks in repo")
        first_id = items[0]["id"]
        result = _call_tool(
            "tm_get_section", {"id": first_id, "section": "Description"}
        )
        assert isinstance(result, dict)
        assert "found" in result

    def test_tm_get_subsection_existing_item(self):
        items = _call_tool("tm_list", {"kind": "task"})
        if not items:
            pytest.skip("No tasks in repo")
        first_id = items[0]["id"]
        result = _call_tool(
            "tm_get_subsection", {"id": first_id, "section_path": "description"}
        )
        assert isinstance(result, dict)
        assert "found" in result

    def test_tm_get_standard_existing(self):
        stds = _call_tool("tm_list_standards")
        if not stds:
            pytest.skip("No standards in repo")
        std_id = stds[0]["id"]
        result = _call_tool("tm_get_standard", {"standard_id": std_id})
        assert "item" in result
        assert "body" in result


# ---------------------------------------------------------------------------
# 3. Mutation tools — require isolated project (cwd=tmp_path)
# ---------------------------------------------------------------------------

class TestMCPMutationIsolated:
    """Mutation tests that require a fully isolated MCP project."""

    def test_tm_new_request_creates_item(self, isolated_project):
        result = _call_tool(
            "tm_new_request",
            _request_args("MCP Isolated Request", "Created by isolated MCP test"),
            cwd=isolated_project,
        )
        assert "id" in result
        assert result["id"].startswith("request-")

    def test_tm_new_request_persists_source_and_context(self, isolated_project):
        _call_tool(
            "tm_new_request",
            {
                "label": "Traceable MCP Request",
                "summary": "Created by isolated MCP test",
                "source": "mcp",
                "context": "integration test",
            },
            cwd=isolated_project,
        )
        shown = _call_tool("tm_show", {"id": "request-0001"}, cwd=isolated_project)
        assert shown["source"] == "mcp"
        assert shown["context"] == "integration test"

    def test_tm_new_spec_creates_item(self, isolated_project):
        result = _call_tool(
            "tm_new_spec",
            {"label": "Isolated Spec", "summary": "MCP spec test"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("spec-")

    def test_tm_new_plan_creates_item(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        result = _call_tool(
            "tm_new_plan",
            {"label": "Isolated Plan", "summary": "MCP plan test", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("plan-")

    def test_tm_new_task_creates_item(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        result = _call_tool(
            "tm_new_task",
            {"label": "Isolated Task", "summary": "MCP task test", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("task-")

    def test_tm_new_wp_creates_item(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        _call_tool(
            "tm_new_plan",
            {"label": "PL", "summary": "P", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_new_wp",
            {"label": "Isolated WP", "summary": "MCP wp test", "plan": "plan-0001"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("wp-")

    def test_tm_new_standard_creates_item(self, isolated_project):
        result = _call_tool(
            "tm_new_standard",
            {"label": "Isolated Standard", "summary": "MCP standard test"},
            cwd=isolated_project,
        )
        assert result["id"].startswith("standard-")

    def test_tm_state_changes_state(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        result = _call_tool(
            "tm_state", {"id": "spec-0001", "new_state": "ready"}, cwd=isolated_project
        )
        assert result["state"] == "ready"

    def test_tm_update_label(self, isolated_project):
        _call_tool(
            "tm_new_request",
            _request_args("Original", "S"),
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_update",
            {"id": "request-0001", "label": "Updated"},
            cwd=isolated_project,
        )
        assert "id" in result

    def test_tm_update_append(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        result = _call_tool(
            "tm_update",
            {"id": "request-0001", "append": "## Extra\n\nAppended."},
            cwd=isolated_project,
        )
        assert "id" in result
        content = _call_tool(
            "tm_get_content", {"id": "request-0001"}, cwd=isolated_project
        )
        assert "Appended." in content

    def test_tm_batch_update_state_and_summary(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        _call_tool(
            "tm_new_task",
            {"label": "T", "summary": "Old", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        _call_tool(
            "tm_state", {"id": "task-0001", "new_state": "ready"}, cwd=isolated_project
        )
        result = _call_tool(
            "tm_batch_update",
            {
                "id": "task-0001",
                "operations": [
                    {"op": "state", "value": "in_progress"},
                    {"op": "summary", "value": "New summary"},
                ],
            },
            cwd=isolated_project,
        )
        assert "results" in result

    def test_tm_move_task_to_contrib(self, isolated_project):
        (isolated_project / "docs" / "planning" / "tasks" / "contrib").mkdir(
            parents=True, exist_ok=True
        )
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        _call_tool(
            "tm_new_task",
            {"label": "T", "summary": "S", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_move", {"id": "task-0001", "domain": "contrib"}, cwd=isolated_project
        )
        assert "contrib" in result.get("path", "")

    def test_tm_relink_request_refs(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        result = _call_tool(
            "tm_relink",
            {"src": "spec-0001", "field": "request_refs", "dst": "request-0001"},
            cwd=isolated_project,
        )
        assert "id" in result

    def test_tm_package_groups_tasks(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        _call_tool(
            "tm_new_plan",
            {"label": "PL", "summary": "P", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        _call_tool(
            "tm_new_task",
            {"label": "T1", "summary": "S", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        _call_tool(
            "tm_new_task",
            {"label": "T2", "summary": "S", "spec": "spec-0001"},
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_package",
            {
                "plan": "plan-0001",
                "tasks": ["task-0001", "task-0002"],
                "label": "WP",
                "summary": "S",
            },
            cwd=isolated_project,
        )
        assert result["id"].startswith("wp-")

    def test_tm_delete_soft(self, isolated_project):
        _call_tool(
            "tm_new_request",
            _request_args("ToDelete", "S"),
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_delete",
            {"id": "request-0001", "reason": "test cleanup"},
            cwd=isolated_project,
        )
        assert result["hard_delete"] is False

    def test_tm_delete_hard(self, isolated_project):
        _call_tool(
            "tm_new_request",
            _request_args("ToHardDelete", "S"),
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_delete",
            {"id": "request-0001", "hard": True, "reason": "test"},
            cwd=isolated_project,
        )
        assert result["hard_delete"] is True

    def test_tm_update_content_replace(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        result = _call_tool(
            "tm_update_content",
            {
                "id": "request-0001",
                "content": "# Notes\n\nReplaced.\n",
                "mode": "replace",
            },
            cwd=isolated_project,
        )
        assert "id" in result
        content = _call_tool(
            "tm_get_content", {"id": "request-0001"}, cwd=isolated_project
        )
        assert "Replaced." in content

    def test_tm_update_content_append(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        _call_tool(
            "tm_update_content",
            {
                "id": "request-0001",
                "content": "# Base\n\nBase content.\n",
                "mode": "replace",
            },
            cwd=isolated_project,
        )
        _call_tool(
            "tm_update_content",
            {
                "id": "request-0001",
                "content": "## Appended\n\nExtra.\n",
                "mode": "append",
            },
            cwd=isolated_project,
        )
        content = _call_tool(
            "tm_get_content", {"id": "request-0001"}, cwd=isolated_project
        )
        assert "Extra." in content

    def test_tm_set_section(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        _call_tool(
            "tm_update_content",
            {
                "id": "spec-0001",
                "content": "# Purpose\n\nOld.\n\n# Scope\n\nScope.\n",
                "mode": "replace",
            },
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_set_section",
            {
                "id": "spec-0001",
                "section": "Purpose",
                "content": "New purpose content.",
            },
            cwd=isolated_project,
        )
        assert isinstance(result, dict)
        content = _call_tool(
            "tm_get_content", {"id": "spec-0001"}, cwd=isolated_project
        )
        assert "New purpose content." in content

    def test_tm_append_section(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        _call_tool(
            "tm_update_content",
            {
                "id": "spec-0001",
                "content": "# Notes\n\nBase note.\n",
                "mode": "replace",
            },
            cwd=isolated_project,
        )
        _call_tool(
            "tm_append_section",
            {"id": "spec-0001", "section": "Notes", "content": "Additional note."},
            cwd=isolated_project,
        )
        content = _call_tool(
            "tm_get_content", {"id": "spec-0001"}, cwd=isolated_project
        )
        assert "Additional note." in content

    def test_tm_create_with_content(self, isolated_project):
        result = _call_tool(
            "tm_create_with_content",
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
        content = _call_tool(
            "tm_get_content", {"id": result["id"]}, cwd=isolated_project
        )
        assert "The problem." in content

    def test_tm_claim_and_unclaim(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        claim_result = _call_tool(
            "tm_claim",
            {"kind": "spec", "id": "spec-0001", "holder": "agent-test", "ttl": 300},
            cwd=isolated_project,
        )
        assert claim_result["holder"] == "agent-test"
        active = _call_tool("tm_claims", {"kind": "spec"}, cwd=isolated_project)
        assert any(c["id"] == "spec-0001" for c in active)
        unclaim_result = _call_tool(
            "tm_unclaim", {"id": "spec-0001"}, cwd=isolated_project
        )
        assert unclaim_result is True
        after = _call_tool("tm_claims", {"kind": "spec"}, cwd=isolated_project)
        assert not any(c["id"] == "spec-0001" for c in after)

    def test_tm_validate_after_create(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        errors = _call_tool("tm_validate", cwd=isolated_project)
        assert isinstance(errors, list)

    def test_tm_index_runs_without_error(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        # tm_index returns None
        resp = _call_tool_raw("tm_index", {}, cwd=isolated_project)
        assert "error" not in resp

    def test_tm_reconcile_returns_dict(self, isolated_project):
        result = _call_tool("tm_reconcile", cwd=isolated_project)
        assert isinstance(result, dict)
        assert "orphans" in result

    def test_tm_events_after_create(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        events = _call_tool("tm_events", {"tail": 5}, cwd=isolated_project)
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_tm_verify_structure_isolated(self, isolated_project):
        result = _call_tool("tm_verify_structure", cwd=isolated_project)
        assert isinstance(result, dict)
        assert "healthy" in result

    def test_tm_list_after_mutations(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R1", "S"), cwd=isolated_project
        )
        _call_tool(
            "tm_new_request", _request_args("R2", "S"), cwd=isolated_project
        )
        result = _call_tool("tm_list", {"kind": "request"}, cwd=isolated_project)
        assert len(result) >= 2

    def test_tm_show_after_create(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("ShowMe", "S"), cwd=isolated_project
        )
        result = _call_tool("tm_show", {"id": "request-0001"}, cwd=isolated_project)
        assert result["id"] == "request-0001"
        assert result["label"] == "ShowMe"

    def test_tm_status_after_create(self, isolated_project):
        _call_tool(
            "tm_new_request", _request_args("R", "S"), cwd=isolated_project
        )
        result = _call_tool("tm_status", cwd=isolated_project)
        assert result.get("request", {}).get("captured", 0) >= 1

    def test_tm_new_request_duplicate_detection(self, isolated_project):
        """Duplicate requests should return existing item with created=False."""
        _call_tool(
            "tm_new_request",
            _request_args("Dup Label", "S"),
            cwd=isolated_project,
        )
        result = _call_tool(
            "tm_new_request",
            _request_args("Dup Label", "S"),
            cwd=isolated_project,
        )
        assert result.get("created") is False
        assert "duplicate_of" in result

    def test_tm_state_invalid_transition_returns_error(self, isolated_project):
        _call_tool("tm_new_spec", {"label": "SP", "summary": "S"}, cwd=isolated_project)
        resp = _call_tool_raw(
            "tm_state", {"id": "spec-0001", "new_state": "done"}, cwd=isolated_project
        )
        has_error = "error" in resp or resp.get("result", {}).get("isError")
        assert has_error, "Expected error for invalid state transition (draft→done)"

    def test_tm_new_standard_and_get(self, isolated_project):
        _call_tool(
            "tm_new_standard",
            {"label": "Code Style", "summary": "Use consistent formatting"},
            cwd=isolated_project,
        )
        stds = _call_tool("tm_list_standards", cwd=isolated_project)
        assert any(s["id"] == "standard-0001" for s in stds)
        std = _call_tool(
            "tm_get_standard", {"standard_id": "standard-0001"}, cwd=isolated_project
        )
        assert std["item"]["kind"] == "standard"
