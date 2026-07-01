"""Agents operational MCP server — profile resolution for job execution."""
from __future__ import annotations

from audiagentic.components.agents import agents_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def agent_resolve_profile(profile_id: str) -> dict:
    return agents_api.resolve_profile(project_root_from_env(), profile_id)


@mcp.tool()
@log_tool_call
def agent_resolve_default_profile() -> dict:
    return agents_api.resolve_default_profile(project_root_from_env())


@mcp.tool()
@log_tool_call
def agent_list_profiles() -> list:
    return agents_api.list_profiles(project_root_from_env())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("agents")
    mcp.run()


if __name__ == "__main__":
    main()
