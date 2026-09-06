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
    from audiagentic.components.agents.configuration.global_catalog import (
        list_global_agent_definitions,
    )

    definitions = list_global_agent_definitions(project_root_from_env())
    return _sparse([_agent_card(definition) for definition in definitions])


@mcp.tool()
@tool_boundary
def agent_task_status(request_id: str) -> dict[str, Any]:
    """Return the compact task status used for normal MCP polling.

    V4 is the only public projection: lifecycle, activity, bounded latest
    activity type, progress sequence/timestamp, and terminal outcome only. Response content,
    diagnostics, attempts, watchdog policy, and provider internals belong to
    their separate operations and never cross the normal status boundary.
    """
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
    """Return bounded semantic failure/activity evidence for one request.

    Unlike ``agent_task_status`` this is an operator diagnostic surface.  It
    is still bounded and redacted: no prompt, full response, DOM, CDP handle,
    cookie, or traceback crosses the MCP boundary.
    """
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
    """Request a safe diagnostic recovery action.

    Supported actions are ``reconcile``, ``abandon`` and
    ``clear-not-submitted``. Recovery never resends a provider prompt; callers
    continue polling status/diagnostics for the resulting lifecycle evidence.
    """
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
    """Return the exact terminal response through the server-side boundary.

    The gateway resolves and verifies the request-owned artifact internally.
    No filesystem path, URI, preview, or alternate artifact locator crosses
    MCP; this operation is the sole full-response surface.
    """
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
    """List persisted gateway requests, most recently created first.

    Optionally filter by state (queued/running/completed/failed/cancelled/
    rejected). Reads from disk, so this works even for requests from an
    earlier process — unlike queue depths, which are in-memory only.
    """
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
    """Operator-facing summary: persisted request counts by state, the 5 most
    recent failures (with redacted error), and in-process per-profile queue depths."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("gateway_overview", project_root))


@mcp.tool()
@tool_boundary
def agent_task_session_list(state: str | None = None) -> list[dict[str, Any]]:
    """List persisted gateway sessions in stable lifecycle/ID order. Each entry carries a
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
    model_id: str | None = None,
    component_profile: str | None = None,
) -> dict[str, Any]:
    """Resume a validated durable provider conversation in a new session."""
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
    """Submit async work as `agent_id` (AS62's Agent Definition — an Execution
    Profile plus a Role bundled under one stable ID). Resolves the agent's
    execution profile and dispatches.

    Response fields:
      request-id:       unique identifier for this request
      state:            current state ("queued")
      session-id:       session identifier — auto-generated when session_keep_alive
                        or provider policy requires it; GPT always retains one
      metadata:         sanitized metadata supplied on submit; omitted when empty
      provider-metadata: adapter-owned session metadata; omitted when unavailable

    Immediately — poll with `agent_task_status` using the returned request-id.
    Raises RES-AGD-001 if `agent_id` is not a configured
    agent definition.

    `provider_chat_url` may seed a GPT-auto session from a full
    project-scoped ChatGPT conversation URL (`/g/<project>/c/<id>`).

    `title` supplies a dashboard request label (1–120 single-line characters),
    overriding the provider label without modifying the prompt or remote chat.

    GPT requests without a session reuse this client's default per project/agent.
    Use new_session=true for a separate chat; it does not replace an established
    default. Explicit session_id or provider_chat_url also leaves that default
    unchanged. The first admitted session establishes the default. Recovery
    fallback warnings are returned on submission or subsequent task status.

    For GPT, session_keep_alive=false does NOT disable default-session reuse
    or close the chat immediately. It releases the live handle after the
    execution profile's idle timeout (30 minutes if unset/disabled), only
    when no turn is active or queued. Results and chat references are retained;
    a later request can auto-resume the idle-closed conversation.
    source is optional provenance text, not a client/session identifier.
    workspace_name supplies the GPT project name, not a session reuse key.

    This is the sole submission surface over MCP (RV891). Direct
    provider/model execution bypassing agent selection is not exposed over MCP."""
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

