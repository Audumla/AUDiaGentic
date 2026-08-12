"""LSP code-intelligence MCP server.

A deliberately small, practical surface for agents: five tools, each with a
`kind`/`action`/`paths` option instead of a separate tool per LSP method.

- lsp_diagnostics  — what's broken (repo / file / changed set)
- lsp_symbol_context — understand a symbol (type, definition, references) in one call
- lsp_navigate      — follow a relationship (definition, references, callers, subtypes, …)
- lsp_symbols       — find symbols (workspace search or one file's outline)
- lsp_edit          — preview an LSP-computed edit (format / organize imports / rename / quick-fix)
"""
from __future__ import annotations

import atexit
from typing import Any

from audiagentic.components.coding_lsp import lsp_api
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


def _teardown() -> None:
    lsp_api.shutdown_all_sessions()


atexit.register(_teardown)


@mcp.tool()
@tool_boundary
def lsp_diagnostics(
    paths: list[str] | None = None,
    root: str = ".",
    min_severity: int = 4,
    limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Report problems (errors/warnings) the language server sees — agents are otherwise blind to these.

    paths: omitted/empty = scan the whole repo; one path = just that file (waits for
        a fresh check, use right after editing it); several = only those files.
    min_severity: 1=error, 2=warning, 3=info, 4=hint (default 4 returns everything).
    limit: 0 = no cap. Returns {file: [diagnostic, …]}.
    """
    paths = paths or []
    if not paths:
        return lsp_api.diagnostics(root, min_severity=min_severity, limit=limit)
    if len(paths) == 1:
        return {paths[0]: lsp_api.file_diagnostics(paths[0], min_severity=min_severity)}
    return lsp_api.changed_diagnostics(paths, min_severity=min_severity, limit=limit)


@mcp.tool()
@tool_boundary
def lsp_symbol_context(file: str, position: str) -> dict[str, Any]:
    """Understand the symbol at a position in one call — the go-to "what is this?" tool.

    Bundles the type/signature (hover), where it is defined, and who references it.
    position: "line:col" (1-based line). Returns {hover, definitions, references, referenceCount}.
    """
    return lsp_api.symbol_context(file, position)


_NAVIGATE = {
    "definition": lambda f, p: lsp_api.definition(f, p),
    "references": lambda f, p: lsp_api.references(f, p),
    "type": lambda f, p: lsp_api.type_definition(f, p),
    "implementations": lambda f, p: lsp_api.implementation(f, p),
    "callers": lambda f, p: lsp_api.call_hierarchy(f, p, direction="incoming"),
    "callees": lambda f, p: lsp_api.call_hierarchy(f, p, direction="outgoing"),
    "supertypes": lambda f, p: lsp_api.type_hierarchy(f, p, direction="supertypes"),
    "subtypes": lambda f, p: lsp_api.type_hierarchy(f, p, direction="subtypes"),
}


@mcp.tool()
@tool_boundary
def lsp_navigate(file: str, position: str, kind: str = "definition") -> list[dict[str, Any]]:
    """Follow a code relationship from the symbol at a position.

    kind: definition | references | type | implementations | callers | callees |
        supertypes | subtypes. position: "line:col". Returns a list of locations.
    """
    op = _NAVIGATE.get(kind)
    if op is None:
        return [{"error": f"unknown kind {kind!r}; expected one of {sorted(_NAVIGATE)}"}]
    return op(file, position)


@mcp.tool()
@tool_boundary
def lsp_symbols(query: str = "", file: str | None = None, root: str = ".") -> list[dict[str, Any]]:
    """Find symbols by name across the workspace, or list one file's outline.

    Pass `file` for that file's symbol outline; otherwise search the workspace by `query`.
    Returns a list of {name, kind, location}.
    """
    if file is not None:
        return lsp_api.document_symbols(file)
    return lsp_api.workspace_symbols(query, root)


@mcp.tool()
@tool_boundary
def lsp_edit(
    file: str,
    action: str,
    position: str | None = None,
    new_name: str | None = None,
    range_start: str | None = None,
    range_end: str | None = None,
    only: list[str] | None = None,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Preview an LSP-computed edit (returns the proposed change; does not apply it).

    action:
      - format            — reformat the file, or range_start..range_end if given
      - organize_imports  — sort and prune imports
      - rename            — rename across the repo; requires position + new_name
      - code_action       — quick-fixes for range_start..range_end (filter kinds with `only`)
    positions/ranges are "line:col". Returns the proposed workspace edit for review.
    """
    if action == "format":
        return lsp_api.format_preview(file, range_start=range_start, range_end=range_end)
    if action == "organize_imports":
        return lsp_api.organize_imports_preview(file)
    if action == "rename":
        if position is None or new_name is None:
            return {"error": "rename requires 'position' and 'new_name'"}
        return lsp_api.rename_preview(file, position, new_name)
    if action == "code_action":
        return lsp_api.code_actions(file, range_start=range_start, range_end=range_end, only=only)
    return {"error": f"unknown action {action!r}; expected format|organize_imports|rename|code_action"}


def main() -> None:
    """Entry point for harness invocation."""
    run_mcp_server(mcp, "coding-lsp")


if __name__ == "__main__":
    main()
