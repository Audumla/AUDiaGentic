"""Privileged Agents administration MCP boundary placeholder."""
from __future__ import annotations

from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


def _call(name: str, *args, **kwargs):
    from audiagentic.components.agents.gateway import management_api
    return getattr(management_api, name)(project_root_from_env(), *args, **kwargs)


@mcp.tool()
@tool_boundary
def agent_gateway_status() -> dict:
    return _call("gateway_status")


@mcp.tool()
@tool_boundary
def agent_gateway_list_implementations() -> dict:
    return _call("gateway_list_implementations")


@mcp.tool()
@tool_boundary
def agent_gateway_select_implementation(implementation_id: str) -> dict:
    return _call("gateway_select_implementation", implementation_id)


@mcp.tool()
@tool_boundary
def agent_gateway_get_config(implementation_id: str | None = None) -> dict:
    return _call("gateway_get_config", implementation_id)


@mcp.tool()
@tool_boundary
def agent_gateway_set_config(implementation_id: str, updates: dict) -> dict:
    return _call("gateway_set_config", implementation_id, updates)


@mcp.tool()
@tool_boundary
def agent_gateway_get_retention_policy() -> dict:
    return _call("gateway_get_retention_policy")


@mcp.tool()
@tool_boundary
def agent_gateway_create_operation(operation_id: str, kind: str, scope: dict, correlation_id: str | None = None) -> dict:
    return _call("gateway_create_operation", operation_id=operation_id, kind=kind, scope=scope, correlation_id=correlation_id)


@mcp.tool()
@tool_boundary
def agent_gateway_get_operation(operation_id: str) -> dict:
    return _call("gateway_get_operation", operation_id)


@mcp.tool()
@tool_boundary
def agent_gateway_list_operations(limit: int = 100) -> list[dict]:
    return _call("gateway_list_operations", limit=limit)


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
