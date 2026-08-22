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
    """List available agents — the valid `agent_id` values for
    `agent_task_submit` — as a slim, client-facing summary per agent
    (agent_id, name, description, skills). Modeled on the A2A AgentCard
    shape: what an agent IS to a caller, not how it's implemented —
    execution profile, role, and other harness wiring are deliberately
    left out.

    The configuration MCP server (ag-agents-config) separately exposes the
    full administrative record (via `agent_list_definitions`) for managing
    definitions/execution-profiles/roles; a tool name must have exactly one
    owning MCP surface, so this copy is named agent_task_list_definitions.
    It exists so a caller using ONLY the gateway server can discover valid
    agent_id values without also needing the configuration server
    attached."""
    from audiagentic.components.agents.configuration.global_catalog import list_global_agent_definitions

    definitions = list_global_agent_definitions(project_root_from_env())
    return _sparse([_agent_card(definition) for definition in definitions])


@mcp.tool()
@tool_boundary
def agent_task_status(request_id: str) -> dict[str, Any]:
    """Return the current persisted state of a gateway request."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("get_execution_request", project_root, request_id))


@mcp.tool()
@tool_boundary
def agent_task_cancel(request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("cancel_execution_request", project_root, request_id))


@mcp.tool()
@tool_boundary
def agent_task_list_requests(
    state: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """List persisted gateway requests, most recently created first.

    Optionally filter by state (queued/running/completed/failed/cancelled/
    rejected). Reads from disk, so this works even for requests from an
    earlier process — unlike queue depths, which are in-memory only.
    """
    project_root = project_root_from_env()
    return _sparse(
        call_gateway_method("list_execution_requests", project_root, state=state, limit=limit)
    )


@mcp.tool()
@tool_boundary
def agent_task_gateway_overview() -> dict[str, Any]:
    """Operator-facing summary: persisted request counts by state, the 5 most
    recent failures (with redacted error), and in-process per-profile queue depths."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("gateway_overview", project_root))


@mcp.tool()
@tool_boundary
def agent_task_session_list(state: str | None = None) -> list[dict[str, Any]]:
    """List persisted gateway sessions, newest first. Each entry carries a
    'live' flag: true when the session's agent process is held by this gateway
    process (only live sessions can accept new turns)."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("list_execution_sessions", project_root, state=state))


@mcp.tool()
@tool_boundary
def agent_task_session_close(session_id: str) -> dict[str, Any]:
    """Close a live agent session (terminates its agent process). Idempotent —
    an already-closed or orphaned session returns its final record."""
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
    """Issue a closed generic session control and return its acknowledgement.

    The acknowledgement never claims the turn/session reached a lifecycle
    state; callers continue to observe that through request status.
    """
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
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
    model_id: str | None = None,
    component_profile: str | None = None,
) -> dict[str, Any]:
    """Resume a validated durable provider conversation in a new session."""
    project_root = project_root_from_env()
    kwargs: dict[str, Any] = {
        "control_id": control_id,
        "identity_context_fingerprint": identity_context_fingerprint,
        "execution_context_fingerprint": execution_context_fingerprint,
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
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
    execution_context_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Submit async work as `agent_id` (AS62's Agent Definition — an Execution
    Profile plus a Role bundled under one stable ID). Resolves the agent's
    execution profile and dispatches.

    Response fields:
      request-id:       unique identifier for this request
      state:            current state ("queued")
      session-id:       session identifier — auto-generated when session_keep_alive
                        is true and no session_id is provided; omitted when absent
      metadata:         sanitized metadata supplied on submit; omitted when empty
      provider-metadata: adapter-owned session metadata; omitted when unavailable

    Immediately — poll with `agent_task_status` using the returned request-id.
    Raises RES-AGD-001 if `agent_id` is not a configured
    agent definition.

    This is the sole submission surface over MCP (RV891). Direct
    provider/model execution bypassing agent selection is not exposed over MCP."""
    project_root = project_root_from_env()
    from audiagentic.components.agents.configuration.global_catalog import get_global_agent_definition

    definition = get_global_agent_definition(project_root, agent_id)
    submit_kwargs: dict[str, Any] = {
        "execution_profile_id": definition["execution_profile_id"],
        "prompt_body": prompt_body,
        "timeout_seconds": timeout_seconds,
        "source": source,
        "metadata": metadata,
        "session_id": session_id,
        "session_keep_alive": session_keep_alive,
        "session_idle_timeout_seconds": session_idle_timeout_seconds,
        "session_max_lifetime_seconds": session_max_lifetime_seconds,
    }
    if execution_context_fingerprint is not None:
        submit_kwargs["execution_context_fingerprint"] = execution_context_fingerprint
    status = call_gateway_method("submit_execution_request", project_root, **submit_kwargs)
    return _sparse({
        "request-id": status.get("request-id"),
        "state": status.get("state"),
        "session-id": status.get("session-id"),
        "metadata": status.get("metadata") or {},
        "provider-metadata": status.get("provider-metadata") or {},
    })


def main() -> None:
    run_mcp_server(mcp, "agents-gateway")


if __name__ == "__main__":
    main()
