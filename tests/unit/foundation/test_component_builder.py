from __future__ import annotations

from audiagentic.foundation.components.base import McpServerDeclaration
from audiagentic.foundation.mcp.component_builder import entry_from_mcp_declaration


def test_entry_from_mcp_declaration_includes_repo_root_env(monkeypatch) -> None:
    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", r"H:\development\projects\AUDia\AUDiaGentic")

    decl = McpServerDeclaration(
        name="ag-planning",
        module="audiagentic.components.planning.planning_mcp",
    )

    entry = entry_from_mcp_declaration(decl)

    assert entry.env == {
        "AUDIAGENTIC_REPO_ROOT": r"H:\development\projects\AUDia\AUDiaGentic",
    }


def test_entry_from_mcp_declaration_omits_repo_root_env_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)

    decl = McpServerDeclaration(
        name="ag-planning",
        module="audiagentic.components.planning.planning_mcp",
    )

    entry = entry_from_mcp_declaration(decl)

    assert entry.env == {}
