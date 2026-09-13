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

from audiagentic.components.agents.gateway.client import call_gateway_method
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)

_RESPONSE_PREVIEW_FIELDS = frozenset({"output-preview", "output-truncated"})


def _status_without_response_preview(status: dict[str, Any]) -> dict[str, Any]:
    """Keep MCP status compact and null-free; never spend tokens on a preview."""
    return {
        key: value
        for key, value in status.items()
        if key not in _RESPONSE_PREVIEW_FIELDS and value is not None
    }


def _sparse(value: Any) -> Any:
    """Remove absent values from public MCP payloads without losing false/zero."""
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, raw in value.items():
            cleaned = _sparse(raw)
            if cleaned is None or cleaned == "" or cleaned == {} or cleaned == []:
                continue
            compact[key] = cleaned
        return compact
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _sparse(item)) is not None
            and cleaned != ""
            and cleaned != {}
            and cleaned != []
        ]
    return value


def _agent_card(definition: dict[str, Any]) -> dict[str, Any]:
    """Client-facing summary of one Agent Definition (A2A AgentCard-style
    projection — see protocols/a2a/agent_card.py's build_agent_card for the
    sibling used on the A2A-publication path). Deliberately excludes
    implementation/harness details a calling agent has no use for and must
    not couple to: execution_profile_id, role_ids, prompt_id. What backs an
    agent is free to change without being part of its public contract."""
    return {
        "agent_id": definition["agent_id"],
        "name": definition.get("name"),
        "description": definition.get("description"),
        "skills": [
            {"id": skill, "name": skill} for skill in definition.get("advertised_skills") or []
        ],
    }


@mcp.tool()
@tool_boundary
def agent_task_list_definitions() -> list[dict[str, Any]]:
    """List valid agent_id values with concise names, descriptions, and skills."""
    from audiagentic.components.agents.configuration.global_catalog import (
        list_global_agent_definitions,
    )

    definitions = list_global_agent_definitions(project_root_from_env())
    return _sparse([_agent_card(definition) for definition in definitions])


@mcp.tool()
@tool_boundary
def agent_task_status(request_id: str) -> dict[str, Any]:
    """Poll compact lifecycle status; use diagnostics or response for terminal detail."""
    project_root = project_root_from_env()
    status = call_gateway_method(
        "get_execution_request",
        project_root,
        request_id,
    )
    # V4 is a fixed-shape contract: its inactive axes are explicitly null and
    # must not be removed by the generic sparse projection.
    return _status_without_response_preview(status)


@mcp.tool()
@tool_boundary
def agent_task_diagnostics(request_id: str, limit: int = 25) -> dict[str, Any]:
    """Return bounded, redacted failure and activity evidence for a request."""
    project_root = project_root_from_env()
    return _sparse(
        call_gateway_method(
            "get_execution_diagnostics", project_root, request_id=request_id, limit=limit
        )
    )


@mcp.tool()
@tool_boundary
def agent_task_recover(
    request_id: str,
    action: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Request reconcile, abandon, or clear-not-submitted; recovery never resends a prompt."""
    project_root = project_root_from_env()
    return _sparse(
        call_gateway_method(
            "recover_execution_request",
            project_root,
            request_id=request_id,
            action=action,
            expected_revision=expected_revision,
        )
    )


@mcp.tool()
@tool_boundary
def agent_task_response(request_id: str) -> dict[str, Any]:
    """Return the exact verified terminal response; call only after terminal status."""
    project_root = project_root_from_env()
    text = call_gateway_method("get_execution_response", project_root, request_id)
    raw_bytes = len(text.encode("utf-8"))
    result: dict[str, Any] = {
        "request-id": request_id,
        "delivery": "inline",
        "text": text,
        "bytes": raw_bytes,
    }

    # A full response may belong to a failed terminal attempt (for example,
    # an ACP provider cancelling after a failed tool call).  Keep the response
    # operation self-describing with only the bounded terminal outcome and
    # failure code; the detailed evidence remains on agent_task_diagnostics.
    try:
        diagnostics = call_gateway_method(
            "get_execution_diagnostics", project_root, request_id, limit=1
        )
    except Exception:
        diagnostics = None
    if isinstance(diagnostics, dict):
        state = diagnostics.get("state")
        if isinstance(state, str) and state:
            result["state"] = state
        rollup = diagnostics.get("diagnostics")
        if isinstance(rollup, dict):
            failure_code = rollup.get("failure-code")
            reason_code = rollup.get("reason-code")
            if isinstance(failure_code, str) and failure_code:
                result["error-code"] = failure_code
            if isinstance(reason_code, str) and reason_code:
                result["error-reason"] = reason_code
    return result


@mcp.tool()
@tool_boundary
def agent_task_cancel(request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("cancel_execution_request", project_root, request_id))


@mcp.tool()
@tool_boundary
def agent_task_list_requests(
    state: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List persisted requests, newest first; optionally filter by lifecycle state."""
    project_root = project_root_from_env()
    requests = call_gateway_method(
        "list_execution_requests", project_root, state=state, limit=limit
    )
    projected = [
        _status_without_response_preview(item) if isinstance(item, dict) else item
        for item in requests
    ]
    return projected


@mcp.tool()
@tool_boundary
def agent_task_gateway_overview() -> dict[str, Any]:
    """Return request counts, recent redacted failures, and provider activity."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("gateway_overview", project_root))


@mcp.tool()
@tool_boundary
def agent_task_session_list(state: str | None = None) -> list[dict[str, Any]]:
    """List sessions and whether each is live in this gateway process."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("list_execution_sessions", project_root, state=state))


@mcp.tool()
@tool_boundary
def agent_task_session_close(session_id: str) -> dict[str, Any]:
    """Close a session and its agent process; repeated close is idempotent."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("close_execution_session", project_root, session_id))


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
    return _sparse(
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
    project_root = project_root_from_env()
    kwargs: dict[str, Any] = {
        "control_id": control_id,
        "model_id": model_id,
    }
    if component_profile is not None:
        kwargs["component_profile"] = component_profile
    return _sparse(
        call_gateway_method("resume_execution_session", project_root, source_session_id, **kwargs)
    )


@mcp.tool()
@tool_boundary
def agent_task_submit(
    agent_id: str,
    prompt_body: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    new_session: bool = False,
    workspace_name: str | None = None,
    title: str | None = None,
    execution_context_fingerprint: str | None = None,
    provider_chat_url: str | None = None,
) -> dict[str, Any]:
    """Submit async work for agent_id. Return request-id, then poll status; fetch terminal text with agent_task_response. Set new_session for isolation."""
    project_root = project_root_from_env()
    submit_kwargs: dict[str, Any] = {
        "agent_id": agent_id,
        "prompt_body": prompt_body,
        "source": source,
        "metadata": metadata,
        "session_id": session_id,
        "session_keep_alive": session_keep_alive,
    }
    if new_session:
        submit_kwargs["new_session"] = new_session
    if workspace_name is not None:
        submit_kwargs["workspace_name"] = workspace_name
    if title is not None:
        submit_kwargs["title"] = title
    if execution_context_fingerprint is not None:
        submit_kwargs["execution_context_fingerprint"] = execution_context_fingerprint
    if provider_chat_url is not None:
        submit_kwargs["provider_chat_url"] = provider_chat_url
    status = call_gateway_method("submit_execution_request", project_root, **submit_kwargs)
    return _sparse({
        "request-id": status.get("request-id"),
        "state": status.get("state"),
        "session-id": status.get("session-id"),
        "metadata": status.get("metadata") or {},
        "provider-metadata": status.get("provider-metadata") or {},
        "warnings": status.get("warnings") or [],
    })


def main() -> None:
    run_mcp_server(mcp, "agents-gateway")


if __name__ == "__main__":
    main()

