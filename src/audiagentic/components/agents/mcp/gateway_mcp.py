"""Agent Execution Gateway operational MCP server — agent_id-primary submit
plus status/wait/cancel/list/overview/session (AS63).

`agent_task_submit` is the sole submission tool. The raw, direct
execution_profile_id submission surface (`agent_execution_submit`) was
removed once its only real callers turned out to be its own tests and docs
(AS63 step 7) — direct execution_profile_id submission bypassing Agent
Definition resolution is still available programmatically via
`AgentTaskFactory.submit_raw`/`submit_execution_request`, just not over MCP
(MCP is a deliberately restrictive layer over the fuller Python API).
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
    execution profile and dispatches. Returns {request-id, state, ...}
    immediately — poll with `agent_task_status`/`agent_task_wait` using the
    returned request-id. Raises RES-AGD-001 if `agent_id` is not a configured
    agent definition.

    This is the sole submission surface over MCP (RV891). Direct
    provider/model execution bypassing agent selection is available
    programmatically via `AgentTaskFactory.submit_raw`/
    `submit_execution_request`, not over MCP."""
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
