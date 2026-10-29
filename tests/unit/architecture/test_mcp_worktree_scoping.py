"""Worktree selection is one shared mechanism, never re-implemented per server.

Planning, ledger and gateway servers must be worktree-scoped through
``mcp_server(..., worktree_scoped=True)`` (foundation/mcp/worktree.py), and a
worktree-scoped MCP module must not resolve project roots or call git itself:
that would reintroduce a second, possibly different, answer to "which worktree".
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "audiagentic"
REQUIRED = (
    "components/planning/planning_mcp.py",
    "components/ledger/ledger_mcp.py",
    "components/agents/mcp/gateway_mcp.py",
)
FORBIDDEN = re.compile(
    r"AUDIAGENTIC_REPO_ROOT|discover_checkout_root|find_project_root|\bsubprocess\b|os\.getcwd|Path\.cwd\(\)"
)


def _scoped_modules() -> list[Path]:
    return sorted(
        path for path in SRC.glob("components/**/*_mcp.py")
        if "worktree_scoped=True" in path.read_text(encoding="utf-8")
    )


def test_planning_ledger_and_gateway_servers_are_worktree_scoped():
    scoped = {str(path.relative_to(SRC)) for path in _scoped_modules()}
    assert set(REQUIRED) <= scoped, sorted(set(REQUIRED) - scoped)


def test_worktree_scoped_modules_do_not_resolve_roots_themselves():
    offenders = {
        str(path.relative_to(SRC)): sorted(set(FORBIDDEN.findall(path.read_text(encoding="utf-8"))))
        for path in _scoped_modules()
    }
    assert {name: found for name, found in offenders.items() if found} == {}
