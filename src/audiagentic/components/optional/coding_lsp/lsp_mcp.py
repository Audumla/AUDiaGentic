"""LSP code intelligence MCP server."""
from __future__ import annotations

import atexit
from typing import Any

from audiagentic.components.optional.coding_lsp import lsp_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    run_mcp_server,
)

mcp = mcp_server(__name__)


def _teardown() -> None:
    lsp_api.shutdown_all_sessions()


atexit.register(_teardown)


@mcp.tool()
@log_tool_call
def lsp_capabilities(file: str) -> dict[str, Any]:
    """Show which LSP methods the language server supports for a file.

    Use this to check available capabilities before calling other tools.
    Returns a list of supported method labels (e.g. definition, hover, codeAction).
    """
    return lsp_api.server_capabilities(file)


@mcp.tool()
@log_tool_call
def lsp_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    """Search for workspace-level symbols matching the query string.

    Returns normalized symbols with name, kind, file (repo-relative path), and range.
    Use the returned location to feed position-based tools (lsp_definition, lsp_hover).
    """
    return lsp_api.workspace_symbols(query, root)


@mcp.tool()
@log_tool_call
def lsp_doc_symbols(file: str) -> list[dict[str, Any]]:
    """Get the document outline (symbols tree) for a single file.

    Returns normalized symbols with hierarchical children. Each symbol includes
    name, kind, and range within the file.
    """
    return lsp_api.document_symbols(file)


@mcp.tool()
@log_tool_call
def lsp_definition(file: str, position: str) -> list[dict[str, Any]]:
    """Go to definition of the symbol at the given position.

    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    Returns normalized locations with repo-relative file path and range.
    """
    return lsp_api.definition(file, position)


@mcp.tool()
@log_tool_call
def lsp_hover(file: str, position: str) -> dict[str, Any] | None:
    """Get hover/type information for the symbol at the given position.

    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    Returns normalized hover with contents (string), format (markdown|plaintext), and range.
    """
    return lsp_api.hover(file, position)


@mcp.tool()
@log_tool_call
def lsp_references(
    file: str, position: str, include_declaration: bool = True,
) -> list[dict[str, Any]]:
    """Find all references to the symbol at the given position.

    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    include_declaration: whether to include the symbol's own declaration (default: True).
    Returns normalized locations with repo-relative file path and range.
    """
    return lsp_api.references(file, position, include_declaration)


@mcp.tool()
@log_tool_call
def lsp_type_definition(file: str, position: str) -> list[dict[str, Any]]:
    """Go to type definition of the symbol at the given position.

    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    Returns normalized locations with repo-relative file path and range.
    """
    return lsp_api.type_definition(file, position)


@mcp.tool()
@log_tool_call
def lsp_implementation(file: str, position: str) -> list[dict[str, Any]]:
    """Go to implementation(s) of the symbol at the given position.

    Useful for interfaces/abstract classes to find concrete implementations.
    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    Returns normalized locations with repo-relative file path and range.
    """
    return lsp_api.implementation(file, position)


@mcp.tool()
@log_tool_call
def lsp_call_hierarchy(
    file: str, position: str, direction: str = "incoming",
) -> list[dict[str, Any]]:
    """Get call hierarchy for the symbol at the given position.

    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    direction: "incoming" (who calls this symbol) or "outgoing" (who this symbol calls).
    Returns list of call sites with repo-relative file path and range.
    """
    return lsp_api.call_hierarchy(file, position, direction=direction)


@mcp.tool()
@log_tool_call
def lsp_symbol_context(file: str, position: str) -> dict[str, Any]:
    """Combined summary: hover + definition + references for the symbol at position.

    Use this for a single-call overview of a symbol's context.
    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    Returns normalized hover, definitions, references, and reference count.
    """
    return lsp_api.symbol_context(file, position)


@mcp.tool()
@log_tool_call
def lsp_diagnostics(
    root: str = ".", min_severity: int = 4, limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Get workspace-wide diagnostics from the language server.

    min_severity: filter threshold — 1=Error only, 2=Warning+, 3=Info+, 4=All (default).
    limit: max total diagnostics returned, 0 = unlimited.
    Returns dict mapping file URI to list of diagnostics.
    """
    return lsp_api.diagnostics(root, min_severity=min_severity, limit=limit)


@mcp.tool()
@log_tool_call
def lsp_rename_preview(
    file: str, position: str, new_name: str,
) -> dict[str, Any] | None:
    """Preview the workspace edit for renaming a symbol.

    position: "line:column" string, 1-based (e.g. "10:5" = line 10, column 5).
    new_name: the new identifier name.
    Returns normalized workspace edit with repo-relative file paths.
    Preview only — does not apply changes.
    """
    return lsp_api.rename_preview(file, position, new_name)


@mcp.tool()
@log_tool_call
def lsp_file_diagnostics(
    file: str, min_severity: int = 4, timeout_ms: int = 5000,
) -> list[dict[str, Any]]:
    """Get diagnostics for a single file.

    Opens/syncs the file, waits for publishDiagnostics, returns cached result.
    min_severity: 1=Error only, 2=Warning+, 3=Info+, 4=All (default).
    timeout_ms: max wait time for server to publish (default: 5000ms).
    """
    return lsp_api.file_diagnostics(file, min_severity=min_severity, timeout=timeout_ms / 1000.0)


@mcp.tool()
@log_tool_call
def lsp_changed_diagnostics(
    files: list[str], min_severity: int = 4, limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """Batch diagnostics for changed files.

    Caller supplies the changed-file list (from git status or job context).
    min_severity: 1=Error only, 2=Warning+, 3=Info+, 4=All (default).
    limit: max total diagnostics returned (default: 50).
    """
    return lsp_api.changed_diagnostics(files, min_severity=min_severity, limit=limit)


def main() -> None:
    """Entry point for harness invocation."""
    run_mcp_server(mcp, "coding-lsp")


if __name__ == "__main__":
    main()
