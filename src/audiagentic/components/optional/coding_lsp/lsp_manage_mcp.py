"""LSP component management MCP server."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from audiagentic.components.optional.coding_lsp import lsp_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    run_blocking_with_output,
)

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
@log_tool_call
def lsp_config_status(root: str = ".") -> dict[str, Any]:
    return lsp_api.config_status(root)


@mcp.tool()
@log_tool_call
def lsp_add_language(root: str, language: str) -> dict[str, Any]:
    return lsp_api.add_language(root, language)


@mcp.tool()
@log_tool_call
def lsp_remove_language(root: str, language: str) -> dict[str, Any]:
    return lsp_api.remove_language(root, language)


@mcp.tool()
@log_tool_call
def lsp_list_languages() -> dict[str, Any]:
    return lsp_api.list_languages()


@mcp.tool()
@log_tool_call
async def lsp_install_dependencies(names: list[str], root: str = ".") -> dict[str, Any]:
    resolved = root if root != "." else str(_project_root())
    return await lsp_api.install_lsp_dependencies(
        names, run_with_output=run_blocking_with_output, root=resolved
    )


@mcp.tool()
@log_tool_call
def lsp_list_missing() -> dict[str, Any]:
    return lsp_api.list_missing(str(_project_root()))


def main() -> None:
    """Entry point for standalone invocation."""
    from audiagentic.foundation.logging import bootstrap
    bootstrap("coding-lsp-config")
    mcp.run()


if __name__ == "__main__":
    main()
