"""Worktree selection is one shared mechanism, never re-implemented per server.

Planning, ledger and gateway servers must be declared ``worktree-scoped: true``
in their component YAML (the single source: the server reads it, and
``audiagentic setup`` uses it to decide what may be registered at a harness's
user scope). A worktree-scoped MCP module must not resolve project roots or
call git itself: that would reintroduce a second, possibly different, answer
to "which worktree".
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import all_descriptors

REQUIRED = {"ag-planning", "ag-ledger", "ag-agents-gateway"}
FORBIDDEN = re.compile(
    r"AUDIAGENTIC_REPO_ROOT|discover_checkout_root|find_project_root|\bsubprocess\b|os\.getcwd|Path\.cwd\(\)"
)


def _scoped() -> dict[str, str]:
    register_all_components()
    return {
        server.name: server.module
        for descriptor in all_descriptors().values()
        for server in descriptor.mcp_servers
        if server.worktree_scoped
    }


def test_planning_ledger_and_gateway_servers_are_worktree_scoped():
    assert REQUIRED <= set(_scoped()), sorted(REQUIRED - set(_scoped()))


def test_scoping_is_declared_not_coded():
    src = Path(__file__).resolve().parents[3] / "src" / "audiagentic"
    call = re.compile(r"mcp_server\([^)]*worktree_scoped")
    coded = [str(path.relative_to(src)) for path in src.rglob("*.py") if call.search(path.read_text("utf-8"))]
    assert coded == []


def test_worktree_scoped_modules_do_not_resolve_roots_themselves():
    offenders = {}
    for name, module in _scoped().items():
        source = Path(importlib.util.find_spec(module).origin).read_text(encoding="utf-8")
        found = sorted(set(FORBIDDEN.findall(source)))
        if found:
            offenders[name] = found
    assert offenders == {}
