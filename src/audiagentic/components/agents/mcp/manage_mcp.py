"""Agents component management MCP server — execution profile and role CRUD operations."""
from __future__ import annotations

from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def agent_list_execution_profiles() -> list:
    from audiagentic.components.agents.models.execution_profile_api import (
        list_execution_profiles,
    )
    return list_execution_profiles(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_get_execution_profile(profile_id: str) -> dict:
    from audiagentic.components.agents.models.execution_profile_api import (
        get_execution_profile,
    )
    return get_execution_profile(project_root_from_env(), profile_id)


@mcp.tool()
@tool_boundary
def agent_create_execution_profile(profile: dict) -> dict:
    from audiagentic.components.agents.models.execution_profile_api import (
        create_execution_profile,
    )
    return create_execution_profile(project_root_from_env(), profile)


@mcp.tool()
@tool_boundary
def agent_update_execution_profile(profile_id: str, updates: dict) -> dict:
    from audiagentic.components.agents.models.execution_profile_api import (
        update_execution_profile,
    )
    return update_execution_profile(project_root_from_env(), profile_id, updates)


@mcp.tool()
@tool_boundary
def agent_delete_execution_profile(profile_id: str) -> dict:
    from audiagentic.components.agents.models.execution_profile_api import (
        delete_execution_profile,
    )
    return delete_execution_profile(project_root_from_env(), profile_id)


@mcp.tool()
@tool_boundary
def agent_list_roles() -> list:
    from audiagentic.components.agents.models.role_api import list_roles
    return list_roles(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_get_role(role_id: str) -> dict:
    from audiagentic.components.agents.models.role_api import get_role
    return get_role(project_root_from_env(), role_id)


@mcp.tool()
@tool_boundary
def agent_create_role(role: dict) -> dict:
    from audiagentic.components.agents.models.role_api import create_role
    return create_role(project_root_from_env(), role)


@mcp.tool()
@tool_boundary
def agent_update_role(role_id: str, updates: dict) -> dict:
    from audiagentic.components.agents.models.role_api import update_role
    return update_role(project_root_from_env(), role_id, updates)


@mcp.tool()
@tool_boundary
def agent_delete_role(role_id: str) -> dict:
    from audiagentic.components.agents.models.role_api import delete_role
    return delete_role(project_root_from_env(), role_id)


@mcp.tool()
@tool_boundary
def agent_list_definitions() -> list:
    from audiagentic.components.agents.models.agent_definition_api import (
        list_agent_definitions,
    )
    return list_agent_definitions(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_get_definition(agent_id: str) -> dict:
    from audiagentic.components.agents.models.agent_definition_api import (
        get_agent_definition,
    )
    return get_agent_definition(project_root_from_env(), agent_id)


@mcp.tool()
@tool_boundary
def agent_create_definition(definition: dict) -> dict:
    from audiagentic.components.agents.models.agent_definition_api import (
        create_agent_definition,
    )
    return create_agent_definition(project_root_from_env(), definition)


@mcp.tool()
@tool_boundary
def agent_update_definition(agent_id: str, updates: dict) -> dict:
    from audiagentic.components.agents.models.agent_definition_api import (
        update_agent_definition,
    )
    return update_agent_definition(project_root_from_env(), agent_id, updates)


@mcp.tool()
@tool_boundary
def agent_delete_definition(agent_id: str) -> dict:
    from audiagentic.components.agents.models.agent_definition_api import (
        delete_agent_definition,
    )
    return delete_agent_definition(project_root_from_env(), agent_id)


# SH11 Slice C: generic gateway-management implementation selection/config.
# No implementation-specific tools (e.g. "set automatic startup timeout")
# exist here -- get_config/set_config are the only settable surface, per
# CREATING_A_COMPONENT.md's implementation-backed component rule.


@mcp.tool()
@tool_boundary
def agent_gateway_status() -> dict:
    from audiagentic.components.agents.gateway.management_api import gateway_status
    return gateway_status(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_gateway_list_implementations() -> dict:
    from audiagentic.components.agents.gateway.management_api import (
        gateway_list_implementations,
    )
    return gateway_list_implementations(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_gateway_select_implementation(implementation_id: str) -> dict:
    from audiagentic.components.agents.gateway.management_api import (
        gateway_select_implementation,
    )
    return gateway_select_implementation(project_root_from_env(), implementation_id)


@mcp.tool()
@tool_boundary
def agent_gateway_get_config(implementation_id: str | None = None) -> dict:
    from audiagentic.components.agents.gateway.management_api import gateway_get_config
    return gateway_get_config(project_root_from_env(), implementation_id)


@mcp.tool()
@tool_boundary
def agent_gateway_set_config(implementation_id: str, updates: dict) -> dict:
    from audiagentic.components.agents.gateway.management_api import gateway_set_config
    return gateway_set_config(project_root_from_env(), implementation_id, updates)


def main() -> None:
    run_mcp_server(mcp, "agents-manage")


if __name__ == "__main__":
    main()
