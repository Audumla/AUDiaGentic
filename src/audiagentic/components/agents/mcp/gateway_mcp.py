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

import time
from typing import Any

from audiagentic.components.agents.gateway.client import get_gateway_client
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

mcp = mcp_server(__name__)

# Maximum seconds for a single blocking wait call before the MCP transport
# may kill it.  Individual waits are kept under this so the tool call never
# outlives the transport.
MCP_SINGLE_WAIT_CAP_SECONDS = 120.0

# Terminal states from the gateway workflow (SH18).
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "rejected"})


@mcp.tool()
@log_tool_call
def agent_task_status(request_id: str) -> dict[str, Any]:
    """Return the current persisted state of a gateway request."""
    return get_gateway_client().get_execution_request(project_root_from_env(), request_id)


@mcp.tool()
@log_tool_call
def agent_task_wait(request_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Block until a request reaches a terminal state or timeout.

    Honors the caller's timeout_seconds (capped at 300s server-side). If
    the timeout elapses before the request is terminal, returns the current
    status with wait-timeout=True and progress info — never an MCP error.
    """
    import asyncio

    cap = min(timeout_seconds, 300.0) if timeout_seconds else 300.0
    start = time.monotonic()
    client = get_gateway_client()
    project_root = project_root_from_env()

    while True:
        remaining = cap - (time.monotonic() - start)
        if remaining <= 0:
            break
        wait_for = min(remaining, MCP_SINGLE_WAIT_CAP_SECONDS)
        try:
            result = client.wait_execution_request(project_root, request_id, wait_for)
        except asyncio.TimeoutError:
            # The transport timed out — return current status instead of error.
            remaining = cap - (time.monotonic() - start)
            if remaining <= 0:
                break
            continue

        if result.get("state") in _TERMINAL_STATES:
            return result

        # Non-terminal and transport didn't timeout — caller timed out or
        # we got a partial wait-timeout from the API.
        if remaining <= 0:
            break
        # Still have time; loop for another short poll.

    # Timed out — return current status with wait-timeout and progress.
    result = client.get_execution_request(project_root, request_id)
    result["wait-timeout"] = True
    if "progress" not in result:
        result["progress"] = _request_progress(result)
    return result


def _request_progress(record: dict[str, Any]) -> dict[str, Any]:
    """Compute a progress snapshot for a non-terminal request."""
    state = record.get("state", "unknown")
    started_at = record.get("started-at")
    running_seconds = None
    if started_at:
        from audiagentic.foundation.time import now_iso_z

        try:
            from datetime import datetime, timezone

            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            running_seconds = round((now - started).total_seconds(), 1)
        except Exception:
            pass

    return {
        "phase": "launching" if state == "queued" else "running",
        "state": state,
        "running-seconds": running_seconds,
        "last-progress-at": record.get("updated-at"),
        "stale-progress": False,
    }


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
