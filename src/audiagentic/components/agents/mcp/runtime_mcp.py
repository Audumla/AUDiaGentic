"""Operator-owned Context/Work runtime MCP surface."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.client import get_gateway_client
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def agent_context_open(agent_id: str, title: str | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).open_agent_context(root, agent_id, title)


@mcp.tool()
@tool_boundary
def agent_context_get(context_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).get_agent_context(root, context_id)


@mcp.tool()
@tool_boundary
def agent_work_list() -> list[dict[str, Any]]:
    root = project_root_from_env()
    return get_gateway_client(root).list_agent_work(root)


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
