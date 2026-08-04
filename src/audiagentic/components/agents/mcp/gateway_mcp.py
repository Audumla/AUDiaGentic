"""Agent Execution Gateway operational MCP server — task-primary submit plus
status/wait/cancel/list/overview/session, and the explicit raw submission
surface (AS63 step 7).

`agent_task_submit` is the primary submission tool; `agent_task_status`,
`agent_task_wait`, `agent_task_cancel`, `agent_task_list_requests`,
`agent_task_gateway_overview`, `agent_task_session_list`, and
`agent_task_session_close` are submission-agnostic — they work identically
regardless of which tool created the request, `agent_task_submit` or
`agent_execution_submit`, so there is only one copy of each, named for the
primary surface they're grouped with. `agent_execution_submit` is the
explicit, deliberately lower-level raw surface: direct execution_profile_id
submission, bypassing Agent Definition resolution — a deprecation candidate
expected to be dropped once callers finish migrating to `agent_task_submit`.
"""

from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.client import get_gateway_client
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

mcp = mcp_server(__name__)

# A blocking MCP tool call must not outlive the transport that carries it.
# This is deliberately transport-owned; the in-process client has no cap.
MCP_BLOCKING_TIMEOUT_SECONDS = 300.0


def _mcp_capped(timeout_seconds: float | None) -> float:
    """Cap a blocking wait to what the MCP transport can hold.

    The client transport has its own 30-60s timeout, so an MCP tool call must
    never block indefinitely — it returns a 'running' status instead and the
    caller polls. This constraint belongs to the TRANSPORT, which is why it is
    applied here and not in the core gateway API: an in-process supervisor
    running a long implementation task has no such limit (RV511).
    """
    cap = MCP_BLOCKING_TIMEOUT_SECONDS
    return min(timeout_seconds, cap) if timeout_seconds else cap


@mcp.tool()
@log_tool_call
def agent_execution_submit(
    execution_profile_id: str | None = None,
    prompt_body: str | None = None,
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
) -> dict[str, Any]:
    """Submit an async request directly against an execution_profile_id,
    bypassing Agent Definition resolution — prefer `agent_task_submit` unless
    you need to select a provider/model directly without a configured Agent
    Definition. Returns immediately with request-id and initial state; poll
    with `agent_task_status`/`agent_task_wait` using the returned request-id
    — those operations are identical regardless of which tool submitted the
    request.

    Sessions: session_keep_alive=true opens a live agent session that retains
    conversation context after this request; continue it by passing the
    response's session-id as session_id on later requests. Sessions self-clean
    (idle timeout, default 15 min; max lifetime, default 4 h; pass 0 to
    disable either bound). Turns queue FIFO per session; a processing session
    is never reaped. Close explicitly with agent_task_session_close when a
    block of work is done."""
    return get_gateway_client().submit_execution_request(
        project_root_from_env(),
        execution_profile_id=execution_profile_id,
        prompt_body=prompt_body,
        mode="async",
        timeout_seconds=timeout_seconds,
        source=source,
        metadata=metadata,
        session_id=session_id,
        session_keep_alive=session_keep_alive,
        session_idle_timeout_seconds=session_idle_timeout_seconds,
        session_max_lifetime_seconds=session_max_lifetime_seconds,
    )


@mcp.tool()
@log_tool_call
def agent_task_status(request_id: str) -> dict[str, Any]:
    """Return the current persisted state of a gateway request."""
    return get_gateway_client().get_execution_request(project_root_from_env(), request_id)


@mcp.tool()
@log_tool_call
def agent_task_wait(request_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Block until a request reaches a terminal state or timeout (capped for MCP transport)."""
    return get_gateway_client().wait_execution_request(
        project_root_from_env(), request_id, _mcp_capped(timeout_seconds)
    )


@mcp.tool()
@log_tool_call
def agent_task_cancel(request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested."""
    return get_gateway_client().cancel_execution_request(project_root_from_env(), request_id)


@mcp.tool()
@log_tool_call
def agent_task_list_requests(
    state: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """List persisted gateway requests, most recently created first.

    Optionally filter by state (queued/running/completed/failed/cancelled/
    rejected). Reads from disk, so this works even for requests from an
    earlier process — unlike queue depths, which are in-memory only.
    """
    return get_gateway_client().list_execution_requests(
        project_root_from_env(), state=state, limit=limit
    )


@mcp.tool()
@log_tool_call
def agent_task_gateway_overview() -> dict[str, Any]:
    """Operator-facing summary: persisted request counts by state, the 5 most
    recent failures (with redacted error), and in-process per-profile queue depths."""
    return get_gateway_client().gateway_overview(project_root_from_env())


@mcp.tool()
@log_tool_call
def agent_task_session_list(state: str | None = None) -> list[dict[str, Any]]:
    """List persisted gateway sessions, newest first. Each entry carries a
    'live' flag: true when the session's agent process is held by this gateway
    process (only live sessions can accept new turns)."""
    return get_gateway_client().list_execution_sessions(project_root_from_env(), state=state)


@mcp.tool()
@log_tool_call
def agent_task_session_close(session_id: str) -> dict[str, Any]:
    """Close a live agent session (terminates its agent process). Idempotent —
    an already-closed or orphaned session returns its final record."""
    return get_gateway_client().close_execution_session(project_root_from_env(), session_id)


@mcp.tool()
@log_tool_call
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
) -> dict[str, Any]:
    """Submit async work as `agent_id` (AS62's Agent Definition — an Execution
    Profile plus a Role bundled under one stable ID). Resolves the agent's
    execution profile and dispatches the same way `agent_execution_submit`
    does. Returns {request-id, state, ...} immediately — poll with
    `agent_task_status`/`agent_task_wait` using the returned request-id.
    Raises RES-AGD-001 if `agent_id` is not a configured agent definition.

    This is the primary submission surface (RV891). For direct provider/model
    execution bypassing agent selection, use `agent_execution_submit` with
    `execution_profile_id` instead — a thin, deprecation-candidate surface
    expected to be dropped once callers finish migrating here."""
    from audiagentic.components.agents.models.agent_task_api import (
        AgentTaskFactory,
    )

    task = AgentTaskFactory(project_root_from_env()).submit(
        agent_id,
        prompt_body=prompt_body,
        timeout_seconds=timeout_seconds,
        source=source,
        metadata=metadata,
        session_id=session_id,
        session_keep_alive=session_keep_alive,
        session_idle_timeout_seconds=session_idle_timeout_seconds,
        session_max_lifetime_seconds=session_max_lifetime_seconds,
    )
    return task.status()


def main() -> None:
    run_mcp_server(mcp, "agents-gateway")


if __name__ == "__main__":
    main()
