"""Per-call git worktree selection shared by every worktree-scoped MCP server."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from audiagentic.foundation.components.base import McpServerDeclaration
from audiagentic.foundation.mcp.component_server import mcp_server, project_root_from_env


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "c0")
    other = tmp_path / "feature"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(other))
    return main.resolve(), other.resolve()


def _scoped_server(scoped: bool = True):
    """A server whose (test) declaration sets ``worktree-scoped``."""
    server = mcp_server("tests.unit.foundation.test_mcp_worktree")
    server._decl = McpServerDeclaration(  # the declaration a component YAML would supply
        name="test-worktree", module="tests.unit.foundation.test_mcp_worktree", worktree_scoped=scoped)
    return server


def _server(scoped: bool = True):
    server = _scoped_server(scoped)

    @server.tool()
    def where() -> dict:
        return {"root": str(project_root_from_env())}

    @server.tool()
    def plain() -> str:
        return "ok"

    return server


def _call(server, name: str, arguments: dict) -> dict:
    result = asyncio.run(server.call_tool(name, arguments))
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


def test_tool_acts_on_the_selected_worktree_and_reports_it(repo):
    main, feature = repo
    server = _server()
    for worktree, branch in ((main, "main"), (feature, "feature")):
        result = _call(server, "where", {"worktree": str(worktree)})
        assert result["root"] == str(worktree)
        assert result["worktree"]["path"] == str(worktree)
        assert result["worktree"]["branch"] == branch
        assert len(result["worktree"]["head"]) == 40


def test_non_mapping_results_are_wrapped(repo):
    main, _ = repo
    assert _call(_server(), "plain", {"worktree": str(main)}) == {
        "result": "ok", "worktree": {"path": str(main), "branch": "main", "head": _git(main, "rev-parse", "HEAD")},
    }


def test_omitted_worktree_uses_the_server_project(repo, monkeypatch):
    main, _ = repo
    monkeypatch.chdir(main)
    monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
    assert _call(_server(), "where", {})["worktree"]["path"] == str(main)


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda root, tmp: "relative/path", "CFG-MCPWT-002"),
        (lambda root, tmp: str(tmp / "missing"), "CFG-MCPWT-003"),
        (lambda root, tmp: str(tmp / "plain-dir"), "CFG-MCPWT-004"),
        (lambda root, tmp: str(root / "sub"), "CFG-MCPWT-005"),
    ],
)
def test_unconfirmable_worktrees_are_clear_errors(repo, tmp_path, make, code):
    main, _ = repo
    (tmp_path / "plain-dir").mkdir()
    (main / "sub").mkdir()
    with pytest.raises(Exception) as raised:
        asyncio.run(_server().call_tool("where", {"worktree": make(main, tmp_path)}))
    assert code in str(raised.value)
    if code == "CFG-MCPWT-005":
        assert str(main) in str(raised.value)  # names the root to use instead


def test_no_worktree_and_no_git_project_is_a_clear_error(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
    with pytest.raises(Exception) as raised:
        asyncio.run(_server().call_tool("where", {}))
    assert "CFG-MCPWT-001" in str(raised.value)


def test_schema_exposes_the_shared_parameter_only_on_scoped_servers():
    scoped = {tool.name: tool for tool in asyncio.run(_server().list_tools())}
    properties = scoped["where"].inputSchema["properties"]
    assert properties["worktree"] == {"type": "string"}
    assert "worktree" not in scoped["where"].inputSchema.get("required", [])
    unscoped = {tool.name: tool for tool in asyncio.run(_server(scoped=False).list_tools())}
    assert "worktree" not in unscoped["where"].inputSchema["properties"]


def test_reserved_name_is_rejected_at_registration():
    server = _scoped_server()
    with pytest.raises(ValueError, match="reserved"):
        @server.tool()
        def clash(worktree: str) -> dict:
            return {}


def test_selection_does_not_leak_between_calls(repo):
    main, feature = repo
    server = _server()
    assert _call(server, "where", {"worktree": str(feature)})["root"] == str(feature)
    from audiagentic.foundation.mcp.worktree import current_worktree

    assert current_worktree() is None
    assert _call(server, "where", {"worktree": str(main)})["root"] == str(main)
