"""Release MCP server — release component management."""
from __future__ import annotations

from audiagentic.components.release import release_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def get_release_status() -> dict:
    return release_api.get_status(project_root_from_env())


@mcp.tool()
@log_tool_call
def ensure_release_baseline() -> dict:
    return release_api.ensure_baseline(project_root_from_env())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("release-manage")
    mcp.run()


if __name__ == "__main__":
    main()
