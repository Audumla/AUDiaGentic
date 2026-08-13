"""Operator-owned Context/Work runtime MCP surface."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.client import get_gateway_client
from audiagentic.components.agents.work.work_api import (
    add_message,
    answer,
    cancel,
    get_status,
    list_status,
)
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
def agent_work_submit_packet(context_id: str, packet_id: str, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Submit/replay one deterministic packet as canonical Work."""
    from audiagentic.components.agents.work.work_api import submit_packet

    return submit_packet(
        project_root_from_env(),
        context_id=context_id,
        packet_id=packet_id,
        text=text,
        metadata=metadata,
    )


@mcp.tool()
@tool_boundary
def agent_work_list() -> list[dict[str, Any]]:
    root = project_root_from_env()
    return list_status(root)


@mcp.tool()
@tool_boundary
def agent_work_get(work_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_status(root, work_id)


@mcp.tool()
@tool_boundary
def agent_work_message(work_id: str, message_id: str, text: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    return add_message(
        root, work_id, message_id=message_id, text=text, inputs=inputs,
    )


@mcp.tool()
@tool_boundary
def agent_work_answer(work_id: str, choice: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Answer the Foundation interaction currently blocking Work."""
    return answer(project_root_from_env(), work_id, choice=choice, details=details)


@mcp.tool()
@tool_boundary
def agent_work_cancel(work_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return cancel(root, work_id)


@mcp.tool()
@tool_boundary
def agent_work_output(work_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).read_agent_work_output(root, work_id)


@mcp.tool()
@tool_boundary
def agent_event_failures_list() -> list[dict[str, Any]]:
    """List redacted canonical event-ingress failure records."""
    from audiagentic.components.agents.work.work_api import list_event_failures

    return list_event_failures(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_work_overview() -> dict[str, Any]:
    """Return a redacted Work and canonical event-ingress overview."""
    from audiagentic.components.agents.work.work_api import overview

    return overview(project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_work_submit_child(parent_work_id: str, message_id: str, text: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).submit_agent_work_child(
        root,
        parent_work_id,
        {"message_id": message_id, "text": text, "inputs": inputs or {}, "created_at": f"mcp:{message_id}"},
    )


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
