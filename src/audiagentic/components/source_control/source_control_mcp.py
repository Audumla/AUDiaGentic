"""Source control MCP server — component management and configuration."""
from __future__ import annotations

from audiagentic.components.source_control import source_control_api
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def get_source_control_status() -> dict:
    return source_control_api.get_source_control_status()


@mcp.tool()
@tool_boundary
async def install_dependencies(names: list[str]) -> dict:
    return await source_control_api.install_dependencies(names)


@mcp.tool()
@tool_boundary
async def uninstall_dependencies(names: list[str]) -> dict:
    return await source_control_api.uninstall_dependencies(names)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("source-control")
    mcp.run()


if __name__ == "__main__":
    main()
