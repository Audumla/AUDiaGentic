"""LSP code intelligence MCP server."""
from __future__ import annotations

import atexit
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

from audiagentic.components.optional.coding_lsp import lsp_api
from audiagentic.foundation.mcp.component_server import log_tool_call

mcp = FastMCP("lsp-mcp") if FastMCP else None  # type: ignore[call-arg]


def _teardown() -> None:
    lsp_api.shutdown_all_sessions()


atexit.register(_teardown)


@mcp.tool()  # type: ignore[operator]
@log_tool_call
def lsp_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    return lsp_api.workspace_symbols(query, root)


@mcp.tool()  # type: ignore[operator]
@log_tool_call
def lsp_doc_symbols(file: str) -> list[dict[str, Any]]:
    return lsp_api.document_symbols(file)


@mcp.tool()  # type: ignore[operator]
@log_tool_call
def lsp_definition(file: str, position: str) -> list[dict[str, Any]]:
    return lsp_api.definition(file, position)


@mcp.tool()  # type: ignore[operator]
@log_tool_call
def lsp_hover(file: str, position: str) -> dict[str, Any] | None:
    return lsp_api.hover(file, position)


@mcp.tool()  # type: ignore[operator]
@log_tool_call
def lsp_references(file: str, position: str, include_declaration: bool = True) -> list[dict[str, Any]]:
    return lsp_api.references(file, position, include_declaration)


@mcp.tool()  # type: ignore[operator]
@log_tool_call
def lsp_diagnostics(
    root: str = ".", min_severity: int = 4, limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    return lsp_api.diagnostics(root, min_severity=min_severity, limit=limit)


@mcp.tool()  # type: ignore[operator]
@log_tool_call
def lsp_rename_preview(file: str, position: str, new_name: str) -> dict[str, Any] | None:
    return lsp_api.rename_preview(file, position, new_name)


def main() -> None:
    """Entry point for harness invocation."""
    from audiagentic.foundation.logging import bootstrap
    bootstrap("coding-lsp")
    if mcp is None:
        raise ImportError("mcp package not installed")
    mcp.run()


if __name__ == "__main__":
    main()
