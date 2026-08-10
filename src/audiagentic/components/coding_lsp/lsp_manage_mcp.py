"""LSP component management MCP server."""
from __future__ import annotations

from typing import Any

from audiagentic.components.coding_lsp import lsp_config_api
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def lsp_config_status(root: str = ".") -> dict[str, Any]:
    """Report LSP config and binary availability.

    Missing language-server binaries auto-install on first file-based LSP use;
    status alone should not cause manual install instructions.
    """
    return lsp_config_api.config_status(root)


@mcp.tool()
@tool_boundary
def lsp_list_implementations(root: str = ".") -> dict[str, Any]:
    resolved = root if root != "." else str(project_root_from_env())
    return lsp_config_api.list_implementations(resolved)


@mcp.tool()
@tool_boundary
def lsp_select_implementation(root: str = ".", implementation: str = "") -> dict[str, Any]:
    resolved = root if root != "." else str(project_root_from_env())
    return lsp_config_api.select_implementation(resolved, implementation)


@mcp.tool()
@tool_boundary
def lsp_get_config(root: str = ".", implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config plus the settable-option schema for an LSP implementation.

    The ``schema`` field describes every option the implementation accepts
    (type, description, required, default, allowed values) — e.g. ag-lsp's
    ``mutation-enabled``. Use it to discover what can be set, then pass any
    of those keys to ``lsp_set_config``.
    """
    resolved = root if root != "." else str(project_root_from_env())
    return lsp_config_api.get_config(resolved, implementation_id)


@mcp.tool()
@tool_boundary
def lsp_set_config(root: str = ".", implementation_id: str = "", updates: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate and persist config updates for an LSP implementation.

    See ``lsp_get_config`` for the option schema an implementation accepts.
    """
    resolved = root if root != "." else str(project_root_from_env())
    return lsp_config_api.set_config(resolved, implementation_id, updates or {})


@mcp.tool()
@tool_boundary
async def lsp_add_language(root: str = ".", language: str = "") -> dict[str, Any]:
    """Enable a language and install its language-server dependency if missing."""
    resolved = root if root != "." else str(project_root_from_env())
    return await lsp_config_api.enable_language(resolved, language)


@mcp.tool()
@tool_boundary
def lsp_remove_language(root: str, language: str) -> dict[str, Any]:
    return lsp_config_api.remove_language(root, language)


@mcp.tool()
@tool_boundary
def lsp_set_language_option(root: str, language: str, key: str, value: Any) -> dict[str, Any]:
    return lsp_config_api.set_language_option(root, language, key, value)


@mcp.tool()
@tool_boundary
def lsp_reset_language_option(root: str, language: str, key: str) -> dict[str, Any]:
    return lsp_config_api.reset_language_option(root, language, key)


@mcp.tool()
@tool_boundary
def lsp_list_languages() -> dict[str, Any]:
    return lsp_config_api.list_languages()


@mcp.tool()
@tool_boundary
async def lsp_install_dependencies(names: list[str], root: str = ".") -> dict[str, Any]:
    """Eagerly install configured missing language-server binaries.

    File-based LSP tools already auto-install missing binaries on use. Use this
    tool to pre-install, retry, or make the install explicit.
    """
    resolved = root if root != "." else str(project_root_from_env())
    return await lsp_config_api.install_lsp_dependencies(names, root=resolved)


@mcp.tool()
@tool_boundary
def lsp_list_missing() -> dict[str, Any]:
    """List configured binaries currently missing from PATH.

    Missing binaries auto-install on first file-based LSP use; manual shell
    installation is only a fallback if automation fails.
    """
    return lsp_config_api.list_missing(str(project_root_from_env()))


def main() -> None:
    """Entry point for standalone invocation."""
    from audiagentic.foundation.logging import bootstrap
    bootstrap("coding-lsp-config")
    mcp.run()


if __name__ == "__main__":
    main()
