"""LSP component management MCP server."""
from __future__ import annotations

from typing import Any

from audiagentic.components.coding_lsp import lsp_config_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def lsp_config_status(root: str = ".") -> dict[str, Any]:
    return lsp_config_api.config_status(root)


@mcp.tool()
@log_tool_call
def lsp_list_implementations(root: str = ".") -> dict[str, Any]:
    resolved = root if root != "." else str(project_root_from_env())
    return lsp_config_api.list_implementations(resolved)


@mcp.tool()
@log_tool_call
def lsp_select_implementation(root: str = ".", implementation: str = "") -> dict[str, Any]:
    resolved = root if root != "." else str(project_root_from_env())
    return lsp_config_api.select_implementation(resolved, implementation)


@mcp.tool()
@log_tool_call
async def lsp_add_language(root: str = ".", language: str = "") -> dict[str, Any]:
    """Enable a language and install its server binaries in one step.

    Name only the language (e.g. "python"); dependency ids and binaries are
    resolved and installed automatically. Atomic: if the install fails, the
    language is not left enabled.
    """
    resolved = root if root != "." else str(project_root_from_env())
    return await lsp_config_api.enable_language(resolved, language)


@mcp.tool()
@log_tool_call
def lsp_remove_language(root: str, language: str) -> dict[str, Any]:
    return lsp_config_api.remove_language(root, language)


@mcp.tool()
@log_tool_call
def lsp_set_language_option(root: str, language: str, key: str, value: Any) -> dict[str, Any]:
    return lsp_config_api.set_language_option(root, language, key, value)


@mcp.tool()
@log_tool_call
def lsp_reset_language_option(root: str, language: str, key: str) -> dict[str, Any]:
    return lsp_config_api.reset_language_option(root, language, key)


@mcp.tool()
@log_tool_call
def lsp_list_languages() -> dict[str, Any]:
    return lsp_config_api.list_languages()


@mcp.tool()
@log_tool_call
async def lsp_install_dependencies(names: list[str], root: str = ".") -> dict[str, Any]:
    resolved = root if root != "." else str(project_root_from_env())
    return await lsp_config_api.install_lsp_dependencies(names, root=resolved)


@mcp.tool()
@log_tool_call
def lsp_list_missing() -> dict[str, Any]:
    return lsp_config_api.list_missing(str(project_root_from_env()))


def main() -> None:
    """Entry point for standalone invocation."""
    from audiagentic.foundation.logging import bootstrap
    bootstrap("coding-lsp-config")
    mcp.run()


if __name__ == "__main__":
    main()
