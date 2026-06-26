"""Agents component management MCP server — profile CRUD operations."""
from __future__ import annotations

from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def agent_list_profiles() -> list:
    """List all agent profiles with summary information."""
    from audiagentic.components.agents.agents_api import list_profiles
    return list_profiles(project_root_from_env())


@mcp.tool()
@log_tool_call
def agent_get_profile(profile_id: str) -> dict:
    """Get a specific agent profile by ID."""
    from audiagentic.components.agents.agents_api import get_profile
    return get_profile(project_root_from_env(), profile_id)


@mcp.tool()
@log_tool_call
def agent_create_profile(profile: dict) -> dict:
    """Create a new agent profile.

    Required: profile_id, provider_id, model_id.
    Optional: model_alias, params, is_default, description.
    """
    from audiagentic.components.agents.agents_api import create_profile
    return create_profile(project_root_from_env(), profile)


@mcp.tool()
@log_tool_call
def agent_update_profile(profile_id: str, updates: dict) -> dict:
    """Update an existing agent profile. profile_id is immutable."""
    from audiagentic.components.agents.agents_api import update_profile
    return update_profile(project_root_from_env(), profile_id, updates)


@mcp.tool()
@log_tool_call
def agent_delete_profile(profile_id: str) -> dict:
    """Delete an agent profile by ID."""
    from audiagentic.components.agents.agents_api import delete_profile
    return delete_profile(project_root_from_env(), profile_id)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("agents-manage")
    mcp.run()


if __name__ == "__main__":
    main()
