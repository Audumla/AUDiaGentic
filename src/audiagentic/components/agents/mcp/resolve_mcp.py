"""Agents operational MCP server — execution profile resolution for job execution."""
from __future__ import annotations

from audiagentic.components.agents.models import execution_profile_api as agents_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def agent_resolve_execution_profile(profile_id: str) -> dict:
    return agents_api.resolve_execution_profile(project_root_from_env(), profile_id)


@mcp.tool()
@log_tool_call
def agent_resolve_default_execution_profile() -> dict:
    return agents_api.resolve_default_execution_profile(project_root_from_env())


@mcp.tool()
@log_tool_call
def agent_list_execution_profiles() -> list:
    return agents_api.list_execution_profiles(project_root_from_env())


def main() -> None:
    run_mcp_server(mcp, "agents")


if __name__ == "__main__":
    main()
