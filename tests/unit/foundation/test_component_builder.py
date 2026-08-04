from __future__ import annotations

from audiagentic.foundation.components.base import McpServerDeclaration
from audiagentic.foundation.mcp.component_builder import entry_from_mcp_declaration


def test_entry_from_mcp_declaration_includes_explicit_repo_root(tmp_path) -> None:

    decl = McpServerDeclaration(
        name="ag-planning",
        module="audiagentic.components.planning.planning_mcp",
    )

    project_root = tmp_path / "project"
    entry = entry_from_mcp_declaration(decl, project_root)

    assert entry.env == {
        "AUDIAGENTIC_REPO_ROOT": str(project_root.resolve()),
    }


def test_entry_from_mcp_declaration_requires_project_root() -> None:
    decl = McpServerDeclaration(
        name="ag-planning",
        module="audiagentic.components.planning.planning_mcp",
    )

    import pytest
    with pytest.raises(TypeError):
        entry_from_mcp_declaration(decl)  # type: ignore[call-arg]
