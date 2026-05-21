"""Source control admin MCP server — component management and configuration."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.source_control.bootstrap import detect_availability
from audiagentic.components.optional.source_control.dependencies import (
    detect_missing,
    install_dependencies as _install_dependencies,
    uninstall_dependencies as _uninstall_dependencies,
)
from audiagentic.runtime.mcp.server import mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
def get_source_control_status() -> dict:
    """Return availability of git, gh CLI, and official MCP servers."""
    return {**detect_availability(), "missing-dependencies": detect_missing()}


@mcp.tool()
def install_dependencies(names: list[str]) -> dict:
    """Install source-control dependencies (git, gh, gh-mcp, uv) via host package manager.

    Call only after user confirms which dependencies to install. Use detect_missing in
    get_source_control_status to discover which are absent.
    """
    return _install_dependencies(names)


@mcp.tool()
def uninstall_dependencies(names: list[str]) -> dict:
    """Uninstall source-control dependencies via host package manager.

    Explicit user-requested action only — does NOT run when the component is uninstalled.
    """
    return _uninstall_dependencies(names)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
