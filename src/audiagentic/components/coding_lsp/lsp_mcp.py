"""LSP code intelligence MCP server."""
from __future__ import annotations

import atexit
from typing import Any

from audiagentic.components.coding_lsp import lsp_api
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
    return lsp_api.server_capabilities(file)


@mcp.tool()
@log_tool_call
def lsp_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    return lsp_api.workspace_symbols(query, root)


@mcp.tool()
@log_tool_call
def lsp_doc_symbols(file: str) -> list[dict[str, Any]]:
    return lsp_api.document_symbols(file)


@mcp.tool()
@log_tool_call
def lsp_definition(file: str, position: str) -> list[dict[str, Any]]:
    return lsp_api.definition(file, position)


@mcp.tool()
@log_tool_call
def lsp_hover(file: str, position: str) -> dict[str, Any] | None:
    return lsp_api.hover(file, position)


@mcp.tool()
@log_tool_call
def lsp_references(
    file: str, position: str, include_declaration: bool = True,
) -> list[dict[str, Any]]:
    return lsp_api.references(file, position, include_declaration)


@mcp.tool()
@log_tool_call
def lsp_type_definition(file: str, position: str) -> list[dict[str, Any]]:
    return lsp_api.type_definition(file, position)


@mcp.tool()
@log_tool_call
def lsp_implementation(file: str, position: str) -> list[dict[str, Any]]:
    return lsp_api.implementation(file, position)


@mcp.tool()
@log_tool_call
def lsp_call_hierarchy(
    file: str, position: str, direction: str = "incoming",
) -> list[dict[str, Any]]:
    return lsp_api.call_hierarchy(file, position, direction=direction)


@mcp.tool()
@log_tool_call
def lsp_symbol_context(file: str, position: str) -> dict[str, Any]:
    return lsp_api.symbol_context(file, position)


@mcp.tool()
@log_tool_call
def lsp_code_actions(
    file: str,
    range_start: str | None = None,
    range_end: str | None = None,
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    return lsp_api.code_actions(file, range_start=range_start, range_end=range_end, only=only)


@mcp.tool()
@log_tool_call
def lsp_format_preview(
    file: str,
    range_start: str | None = None,
    range_end: str | None = None,
) -> dict[str, Any] | None:
    return lsp_api.format_preview(file, range_start=range_start, range_end=range_end)


@mcp.tool()
@log_tool_call
def lsp_organize_imports_preview(file: str) -> dict[str, Any] | None:
    return lsp_api.organize_imports_preview(file)


@mcp.tool()
@log_tool_call
def lsp_diagnostics(
    root: str = ".", min_severity: int = 4, limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    return lsp_api.diagnostics(root, min_severity=min_severity, limit=limit)


@mcp.tool()
@log_tool_call
def lsp_rename_preview(
    file: str, position: str, new_name: str,
) -> dict[str, Any] | None:
    return lsp_api.rename_preview(file, position, new_name)


@mcp.tool()
@log_tool_call
def lsp_file_diagnostics(
    file: str, min_severity: int = 4, timeout_ms: int = 5000,
) -> list[dict[str, Any]]:
    return lsp_api.file_diagnostics(file, min_severity=min_severity, timeout=timeout_ms / 1000.0)


@mcp.tool()
@log_tool_call
def lsp_changed_diagnostics(
    files: list[str], min_severity: int = 4, limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    return lsp_api.changed_diagnostics(files, min_severity=min_severity, limit=limit)


@mcp.tool()
@log_tool_call
def lsp_inlay_hints(
    file: str, range_start: str, range_end: str,
) -> list[dict[str, Any]]:
    return lsp_api.inlay_hints(file, range_start, range_end)


@mcp.tool()
@log_tool_call
def lsp_signature_help(file: str, position: str) -> dict[str, Any] | None:
    return lsp_api.signature_help(file, position)


@mcp.tool()
@log_tool_call
def lsp_type_hierarchy(
    file: str, position: str, direction: str = "supertypes",
) -> list[dict[str, Any]]:
    return lsp_api.type_hierarchy(file, position, direction=direction)


@mcp.tool()
@log_tool_call
def lsp_completion(
    file: str, position: str, trigger_character: str | None = None,
) -> list[dict[str, Any]]:
    return lsp_api.completion(file, position, trigger_character=trigger_character)


def main() -> None:
    """Entry point for harness invocation."""
    run_mcp_server(mcp, "coding-lsp")


if __name__ == "__main__":
    main()
