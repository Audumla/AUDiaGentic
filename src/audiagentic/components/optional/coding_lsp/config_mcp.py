"""LSP component management MCP server.

Provides tools for configuring and installing language servers. This server is NOT pushed
to provider surfaces — it is invoked directly by the AUDiaGentic CLI.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from audiagentic.foundation.mcp.component_server import mcp_server, run_blocking_with_output
from audiagentic.components.optional.coding_lsp.config import (
    available_language_specs,
    discover_language_servers,
    read_lsp_config,
    write_lsp_config,
)
from audiagentic.components.optional.coding_lsp.lsp_dependencies import get_lsp_dependencies
from audiagentic.foundation.dependencies import detect_missing, install_dependencies

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
def lsp_config_status(root: str = ".") -> dict[str, Any]:
    """Show configured, detected, and available language servers for a project."""
    project_root = Path(root).resolve()
    lsp_path = project_root / ".coding-lsp" / "lsp.json"
    configured = read_lsp_config(lsp_path)
    available = discover_language_servers(project_root)
    deps = get_lsp_dependencies()
    missing = detect_missing(deps, list(deps.keys()))
    return {
        "project_root": str(project_root),
        "configured": list(configured.keys()),
        "available": {lang: ok for lang, ok in available.items()},
        "missing-dependencies": missing,
    }


@mcp.tool()
def lsp_add_language(root: str, language: str) -> dict[str, Any]:
    """Add a language server to the project's lsp.json configuration."""
    project_root = Path(root).resolve()
    lsp_path = project_root / ".coding-lsp" / "lsp.json"
    specs = available_language_specs()
    if language not in specs:
        return {"ok": False, "error": f"Unknown language: {language}. Available: {list(specs.keys())}"}
    configured = read_lsp_config(lsp_path)
    configured[language] = specs[language]
    write_lsp_config(lsp_path, configured)
    return {"ok": True, "language": language, "path": str(lsp_path)}


@mcp.tool()
def lsp_remove_language(root: str, language: str) -> dict[str, Any]:
    """Remove a language server from the project's lsp.json configuration."""
    project_root = Path(root).resolve()
    lsp_path = project_root / ".coding-lsp" / "lsp.json"
    configured = read_lsp_config(lsp_path)
    if language not in configured:
        return {"ok": False, "error": f"Language not configured: {language}"}
    del configured[language]
    write_lsp_config(lsp_path, configured)
    return {"ok": True, "language": language, "path": str(lsp_path)}


@mcp.tool()
def lsp_list_languages() -> dict[str, Any]:
    """List all available language server options with default configurations."""
    specs = available_language_specs()
    return {
        "languages": {name: {"command": s["command"], "file_extensions": s.get("file_extensions", [])}
                      for name, s in specs.items()},
    }


@mcp.tool()
async def lsp_install_dependencies(names: list[str]) -> dict[str, Any]:
    """Install missing LSP language server dependencies.

    Call only after user confirms which dependencies to install. Use lsp_config_status
    to discover which are absent.
    """
    deps = get_lsp_dependencies()
    return await run_blocking_with_output(
        ctx=None,
        logger="coding-lsp.dependencies.install",
        heartbeat_message="LSP dependency install still running...",
        work=lambda output: install_dependencies(deps, names, on_progress=output),
    )


@mcp.tool()
async def lsp_list_missing() -> dict[str, Any]:
    """List missing LSP language server dependencies for the current project."""
    project_root = _project_root()
    deps = get_lsp_dependencies()
    missing = detect_missing(deps, list(deps.keys()))
    return {
        "project_root": str(project_root),
        "missing": missing,
        "hint": "Use lsp_install_dependencies to install missing servers.",
    }


def main() -> None:
    """Entry point for standalone invocation."""
    mcp.run()


if __name__ == "__main__":
    main()
