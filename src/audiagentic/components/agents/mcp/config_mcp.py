"""Operator-owned canonical Agents configuration MCP surface."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.configuration.configuration_api import AgentsConfigService
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def agent_config_read() -> dict[str, Any]:
    return AgentsConfigService().read(project_root_from_env()).document.to_mapping()


@mcp.tool()
@tool_boundary
def agent_config_describe() -> dict[str, Any]:
    snapshot = AgentsConfigService().read(project_root_from_env())
    return {"contract-version": snapshot.document.contract_version, "digest": snapshot.digest, "kinds": ["prompt", "role", "execution_profile", "agent", "trigger"]}


@mcp.tool()
@tool_boundary
def agent_config_apply(document: dict[str, Any], expected_digest: str | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    service = AgentsConfigService()
    current = service.read(root)
    written = service.apply(root, AgentsConfigDocument.from_mapping(document), expected_digest=expected_digest)
    return {"digest": written.digest, "previous-digest": current.digest}


@mcp.tool()
@tool_boundary
def agent_config_put(kind: str, item: dict[str, Any], expected_digest: str) -> dict[str, Any]:
    return {"digest": AgentsConfigService().put(project_root_from_env(), kind, item, expected_digest=expected_digest).digest}


@mcp.tool()
@tool_boundary
def agent_config_delete(kind: str, item_id: str, expected_digest: str) -> dict[str, Any]:
    return {"digest": AgentsConfigService().delete(project_root_from_env(), kind, item_id, expected_digest=expected_digest).digest}


@mcp.tool()
@tool_boundary
def agent_config_validate(document: dict[str, Any] | None = None) -> list[str]:
    root = project_root_from_env()
    service = AgentsConfigService()
    candidate = AgentsConfigDocument.from_mapping(document) if document is not None else service.read(root).document
    return list(service.validate(candidate))


@mcp.tool()
@tool_boundary
def agent_config_get(kind: str, item_id: str) -> dict[str, Any]:
    return AgentsConfigService().get(project_root_from_env(), kind, item_id)


@mcp.tool()
@tool_boundary
def agent_resolve(agent_id: str) -> dict[str, Any]:
    return AgentsConfigService().resolve(project_root_from_env(), agent_id)


# Configuration CRUD remains on the canonical document boundary.  These
# names are retained as ergonomic MCP operations, but no longer live in the
# mixed management server.
@mcp.tool()
@tool_boundary
def agent_list_execution_profiles() -> list:
    from audiagentic.components.agents.configuration.management import list_execution_profiles
    return list_execution_profiles(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_get_execution_profile(profile_id: str) -> dict:
    from audiagentic.components.agents.configuration.management import get_execution_profile
    return get_execution_profile(project_root_from_env(), profile_id)


@mcp.tool()
@tool_boundary
def agent_create_execution_profile(profile: dict) -> dict:
    from audiagentic.components.agents.configuration.management import create_execution_profile
    return create_execution_profile(project_root_from_env(), profile)


@mcp.tool()
@tool_boundary
def agent_update_execution_profile(profile_id: str, updates: dict) -> dict:
    from audiagentic.components.agents.configuration.management import update_execution_profile
    return update_execution_profile(project_root_from_env(), profile_id, updates)


@mcp.tool()
@tool_boundary
def agent_delete_execution_profile(profile_id: str) -> dict:
    from audiagentic.components.agents.configuration.management import delete_execution_profile
    return delete_execution_profile(project_root_from_env(), profile_id)


@mcp.tool()
@tool_boundary
def agent_list_roles() -> list:
    from audiagentic.components.agents.configuration.management import list_roles
    return list_roles(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_get_role(role_id: str) -> dict:
    from audiagentic.components.agents.configuration.management import get_role
    return get_role(project_root_from_env(), role_id)


@mcp.tool()
@tool_boundary
def agent_create_role(role: dict) -> dict:
    from audiagentic.components.agents.configuration.management import create_role
    return create_role(project_root_from_env(), role)


@mcp.tool()
@tool_boundary
def agent_update_role(role_id: str, updates: dict) -> dict:
    from audiagentic.components.agents.configuration.management import update_role
    return update_role(project_root_from_env(), role_id, updates)


@mcp.tool()
@tool_boundary
def agent_delete_role(role_id: str) -> dict:
    from audiagentic.components.agents.configuration.management import delete_role
    return delete_role(project_root_from_env(), role_id)


@mcp.tool()
@tool_boundary
def agent_list_definitions() -> list:
    from audiagentic.components.agents.configuration.management import list_agent_definitions
    return list_agent_definitions(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_get_definition(agent_id: str) -> dict:
    from audiagentic.components.agents.configuration.management import get_agent_definition
    return get_agent_definition(project_root_from_env(), agent_id)


@mcp.tool()
@tool_boundary
def agent_create_definition(definition: dict) -> dict:
    from audiagentic.components.agents.configuration.management import create_agent_definition
    return create_agent_definition(project_root_from_env(), definition)


@mcp.tool()
@tool_boundary
def agent_update_definition(agent_id: str, updates: dict) -> dict:
    from audiagentic.components.agents.configuration.management import update_agent_definition
    return update_agent_definition(project_root_from_env(), agent_id, updates)


@mcp.tool()
@tool_boundary
def agent_delete_definition(agent_id: str) -> dict:
    from audiagentic.components.agents.configuration.management import delete_agent_definition
    return delete_agent_definition(project_root_from_env(), agent_id)


def main() -> None:
    run_mcp_server(mcp, "agents-config")


if __name__ == "__main__":
    main()
