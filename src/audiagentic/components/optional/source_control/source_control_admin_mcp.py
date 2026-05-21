"""Source control admin MCP server — component management and configuration."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.source_control.bootstrap import (
    bootstrap_source_control,
    detect_availability,
)
from audiagentic.runtime.mcp.server import mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
def get_source_control_status() -> dict:
    """Return availability of git, gh CLI, and official MCP servers."""
    return detect_availability()


@mcp.tool()
def install_source_control_mcp_servers() -> dict:
    """Detect and register official git and GitHub MCP servers into provider settings."""
    return bootstrap_source_control(_project_root())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
