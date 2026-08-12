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
def agent_context_list() -> list[dict[str, Any]]:
    root = project_root_from_env()
    return get_gateway_client(root).list_agent_contexts(root)


@mcp.tool()
@tool_boundary
def agent_context_close(context_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).close_agent_context(root, context_id)


@mcp.tool()
@tool_boundary
def agent_work_submit(context_id: str, message_id: str, text: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).submit_agent_work(
        root,
        context_id,
        {"message_id": message_id, "text": text, "inputs": inputs or {}, "created_at": f"mcp:{message_id}"},
    )


@mcp.tool()
@tool_boundary
def agent_work_list() -> list[dict[str, Any]]:
    root = project_root_from_env()
    return get_gateway_client(root).list_agent_work(root)


@mcp.tool()
@tool_boundary
def agent_work_get(work_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).get_agent_work(root, work_id)


@mcp.tool()
@tool_boundary
def agent_work_message(work_id: str, message_id: str, text: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).add_agent_work_message(
        root,
        work_id,
        {"message_id": message_id, "text": text, "inputs": inputs or {}, "created_at": f"mcp:{message_id}"},
    )


@mcp.tool()
@tool_boundary
def agent_work_cancel(work_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).cancel_agent_work(root, work_id)


@mcp.tool()
@tool_boundary
def agent_work_output(work_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).read_agent_work_output(root, work_id)


@mcp.tool()
@tool_boundary
def agent_work_submit_child(parent_work_id: str, message_id: str, text: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    from audiagentic.components.agents.work.work_api import submit_child

    return submit_child(root, parent_work_id, message_id=message_id, text=text, inputs=inputs)


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
