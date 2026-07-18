"""Agent LLM Gateway operational MCP server — submit/status/wait/cancel/run.

Deliberately audiagentic-scoped (not propagated to providers, unlike
ag-agents): exposing gateway dispatch tools on a provider-propagated server
would let a provider surface recursively invoke the gateway that dispatches
back into providers — a re-entrancy and privilege-scope risk (RV20).
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.agents_gateway_client import get_gateway_client
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
def agent_llm_submit(
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
) -> dict[str, Any]:
    """Submit an async LLM gateway request. Returns immediately with request-id
    and initial state — use agent_llm_status/agent_llm_wait to check progress.

    Sessions: session_keep_alive=true opens a live agent session that retains
    conversation context after this request; continue it by passing the
    response's session-id as session_id on later requests. Sessions self-clean
    (idle timeout, default 15 min; max lifetime, default 4 h; pass 0 to
    disable either bound). Turns queue FIFO per session; a processing session
    is never reaped. Close explicitly with agent_llm_session_close when a
    block of work is done."""
    return get_gateway_client().submit_llm_request(
        project_root_from_env(),
        agent_profile_id=agent_profile_id,
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
def agent_llm_status(request_id: str) -> dict[str, Any]:
    """Return the current persisted state of a gateway request."""
    return get_gateway_client().get_llm_request(project_root_from_env(), request_id)


@mcp.tool()
@log_tool_call
def agent_llm_wait(request_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Block until a request reaches a terminal state or timeout (capped for MCP transport)."""
    return get_gateway_client().wait_llm_request(
        project_root_from_env(), request_id, _mcp_capped(timeout_seconds)
    )


@mcp.tool()
@log_tool_call
def agent_llm_cancel(request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested."""
    return get_gateway_client().cancel_llm_request(project_root_from_env(), request_id)


@mcp.tool()
@log_tool_call
def agent_llm_run(
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
) -> dict[str, Any]:
    """Submit and block until a terminal result or timeout. For one-shot use
    only — not for event-triggered paths (see AG12's async event surface).

    Sessions: session_keep_alive=true opens a live agent session (context is
    retained for follow-up requests via session_id); the transport wait cap
    still applies — long turns should use agent_llm_submit + agent_llm_wait."""
    return get_gateway_client().run_llm_request(
        project_root_from_env(),
        agent_profile_id=agent_profile_id,
        prompt_body=prompt_body,
        timeout_seconds=_mcp_capped(timeout_seconds),
        source=source,
        metadata=metadata,
        session_id=session_id,
        session_keep_alive=session_keep_alive,
        session_idle_timeout_seconds=session_idle_timeout_seconds,
        session_max_lifetime_seconds=session_max_lifetime_seconds,
    )


@mcp.tool()
@log_tool_call
def agent_llm_list_requests(state: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """List persisted gateway requests, most recently created first.

    Optionally filter by state (queued/running/completed/failed/cancelled/
    rejected). Reads from disk, so this works even for requests from an
    earlier process — unlike queue depths, which are in-memory only.
    """
    return get_gateway_client().list_llm_requests(project_root_from_env(), state=state, limit=limit)


@mcp.tool()
@log_tool_call
def agent_llm_gateway_overview() -> dict[str, Any]:
    """Operator-facing summary: persisted request counts by state, the 5 most
    recent failures (with redacted error), and in-process per-profile queue depths."""
    return get_gateway_client().gateway_overview(project_root_from_env())


@mcp.tool()
@log_tool_call
def agent_llm_session_list(state: str | None = None) -> list[dict[str, Any]]:
    """List persisted gateway sessions, newest first. Each entry carries a
    'live' flag: true when the session's agent process is held by this gateway
    process (only live sessions can accept new turns)."""
    return get_gateway_client().list_llm_sessions(project_root_from_env(), state=state)


@mcp.tool()
@log_tool_call
def agent_llm_session_close(session_id: str) -> dict[str, Any]:
    """Close a live agent session (terminates its agent process). Idempotent —
    an already-closed or orphaned session returns its final record."""
    return get_gateway_client().close_llm_session(project_root_from_env(), session_id)


def main() -> None:
    run_mcp_server(mcp, "agents-gateway")


if __name__ == "__main__":
    main()
