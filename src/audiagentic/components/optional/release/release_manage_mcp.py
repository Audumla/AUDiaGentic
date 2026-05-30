"""Release manage MCP server — release component management."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.release import api
from audiagentic.foundation.mcp.component_server import log_tool_call, mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
@log_tool_call
def get_release_status() -> dict:
    """Return release installation status and active manager state."""
    return api.get_status(_project_root())


@mcp.tool()
@log_tool_call
def ensure_release_baseline() -> dict:
    """Ensure the release manager baseline workflow is installed."""
    return api.ensure_baseline(_project_root())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("release-manage")
    mcp.run()


if __name__ == "__main__":
    main()
