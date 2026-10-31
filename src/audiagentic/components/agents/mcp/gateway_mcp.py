"""Agent Execution Gateway operational MCP server — agent_id-primary submit
plus status/cancel/list/overview/session (AS63).

`agent_task_submit` is the sole submission tool. The raw, direct
execution_profile_id submission surface (`agent_execution_submit`) was
removed once its only real callers turned out to be its own tests and docs
(AS63 step 7) — direct execution_profile_id submission bypassing Agent
Definition resolution is still available programmatically through the public
GatewayClient seam, just not over MCP
(MCP is a deliberately restrictive layer over the fuller Python API).
"""

from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.client import (
    call_gateway_method,
    validate_node_selectors,
)
from audiagentic.components.agents.gateway.evidence_projection import (
    project_public_gateway_request,
    project_public_gateway_session,
)
from audiagentic.components.agents.mcp.gateway_mcp_support import (
    _page_limit,
    _request_project_root,
    _session_project_root,
    _status_without_response_preview,
)
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__, structured_output_only=True)


@mcp.tool()
@tool_boundary
def agent_task_list_definitions() -> list[dict[str, Any]]:
    """List valid agent_id values with concise names, descriptions, and skills."""
    return call_gateway_method("list_agent_definition_cards", project_root_from_env())


@mcp.tool()
@tool_boundary
def agent_task_status(request_id: str, include_response: bool = False) -> dict[str, Any]:
    """Poll compact lifecycle status; use diagnostics or response for terminal detail."""
    project_root = _request_project_root(request_id)
    if include_response:
        status = dict(call_gateway_method(
            "get_execution_request", project_root, request_id, include_response=True
        ))
    else:
        # Preserve the pre-v4 call shape for clients and gateway doubles that
        # do not accept the optional response keyword.
        status = dict(call_gateway_method("get_execution_request", project_root, request_id))
    # The compact default is an explicit versioned MCP contract. Callers that
    # need the prior terminal payload use the opt-in flag or response tool.
    status.setdefault("contract-version", "task-status.v4-compact")
    # V4 is a fixed-shape contract: its inactive axes are explicitly null and
    # must not be removed by the generic sparse projection.
    return _status_without_response_preview(status, include_response=include_response)


@mcp.tool()
@tool_boundary
def agent_task_response(request_id: str) -> dict[str, Any]:
    """Return the exact verified terminal response."""
    project_root = _request_project_root(request_id)
    payload = call_gateway_method("get_execution_response_payload", project_root, request_id)
    result: dict[str, Any] = {
        "request-id": request_id,
        "delivery": "inline",
        "text": payload["text"],
        "bytes": payload["bytes"],
        "format": payload["format"],
        "media-type": payload["media_type"],
    }
    state = payload.get("state")
    if isinstance(state, str) and state:
        result["state"] = state
    error_code = payload.get("error_code")
    if isinstance(error_code, str) and error_code:
        result["error-code"] = error_code
    error_reason = payload.get("error_reason")
    if isinstance(error_reason, str) and error_reason:
        result["error-reason"] = error_reason
    return result

@mcp.tool()
@tool_boundary
def agent_task_cancel(request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested."""
    project_root = _request_project_root(request_id)
    return project_public_gateway_request(call_gateway_method("cancel_execution_request", project_root, request_id))


@mcp.tool()
@tool_boundary
def agent_task_list_requests(
    state: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """List persisted requests, newest first; optionally filter by lifecycle state."""
    project_root = project_root_from_env()
    _page_limit(limit)
    requests = call_gateway_method(
        "list_execution_requests", project_root, state=state, limit=limit
    )
    return [_status_without_response_preview(dict(item)) for item in requests]


@mcp.tool()
@tool_boundary
def agent_task_session_list(state: str | None = "active") -> list[dict[str, Any]]:
    """List sessions, defaulting to active; pass a lifecycle state or ``all``."""
    project_root = project_root_from_env()
    gateway_state = None if state == "all" else state
    return [project_public_gateway_session(item) for item in call_gateway_method("list_execution_sessions", project_root, state=gateway_state)]


@mcp.tool()
@tool_boundary
def agent_task_session_close(session_id: str) -> dict[str, Any]:
    """Close a session and its agent process; repeated close is idempotent."""
    project_root = project_root_from_env()
    return project_public_gateway_session(call_gateway_method("close_execution_session", project_root, session_id))


@mcp.tool()
@tool_boundary
def agent_task_session_control(
    session_id: str,
    action: str,
    control_id: str,
    turn_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a session control acknowledgement; poll request status for lifecycle truth."""
    project_root = project_root_from_env()
    return project_public_gateway_request(
        call_gateway_method(
            "control_execution_session",
            project_root,
            session_id,
            action=action,
            control_id=control_id,
            turn_id=turn_id,
            payload=payload,
        )
    )


@mcp.tool()
@tool_boundary
def agent_task_session_resume(
    source_session_id: str,
    control_id: str,
    model_id: str | None = None,
    component_profile: str | None = None,
) -> dict[str, Any]:
    """Resume a validated provider conversation in a new session."""
    project_root = _session_project_root(source_session_id)
    kwargs: dict[str, Any] = {
        "control_id": control_id,
        "model_id": model_id,
    }
    if component_profile is not None:
        kwargs["component_profile"] = component_profile
    return project_public_gateway_session(
        call_gateway_method("resume_execution_session", project_root, source_session_id, **kwargs)
    )


@mcp.tool()
@tool_boundary
def agent_task_submit(
    agent_id: str,
    prompt_body: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    new_session: bool = False,
    title: str | None = None,
    provider_chat_url: str | None = None,
    node_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Submit async work for agent_id. Return request-id, then poll status; fetch terminal text with agent_task_response. Set new_session for isolation.

    node_id/workspace_id are paired recipient IDs, not paths. Node submission
    requires configured caller enrollment and server support; source workspace
    is derived locally, never supplied as a tool parameter. Initial routing
    requires the same enrolled node/workspace. Unsupported targets are rejected
    without falling back to server execution.
    """
    if node_id is not None or workspace_id is not None:
        validate_node_selectors(node_id, workspace_id)
    project_root = project_root_from_env()
    submit_kwargs: dict[str, Any] = {
        "agent_id": agent_id,
        "prompt_body": prompt_body,
        "metadata": metadata,
        "session_id": session_id,
        "session_keep_alive": session_keep_alive,
    }
    if new_session:
        submit_kwargs["new_session"] = new_session
    if title is not None:
        submit_kwargs["title"] = title
    if provider_chat_url is not None:
        submit_kwargs["provider_chat_url"] = provider_chat_url
    if node_id is not None or workspace_id is not None:
        submit_kwargs.update(node_id=node_id, workspace_id=workspace_id)
    status = call_gateway_method("submit_execution_request", project_root, **submit_kwargs)
    return project_public_gateway_request(status)


def main() -> None:
    run_mcp_server(mcp, "agents-gateway")


if __name__ == "__main__":
    main()
