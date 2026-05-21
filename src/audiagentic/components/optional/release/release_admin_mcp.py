"""Release admin MCP server — release component management."""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from audiagentic.components.optional.release import api

mcp = FastMCP("audiagentic-release-admin")


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
def get_release_status() -> dict:
    """Return release installation status and active manager state."""
    return api.get_status(_project_root())


@mcp.tool()
def ensure_release_baseline() -> dict:
    """Ensure the release manager baseline workflow is installed."""
    return api.ensure_baseline(_project_root())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
