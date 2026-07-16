"""Agent LLM Gateway operational MCP server — submit/status/wait/cancel/run.

Deliberately audiagentic-scoped (not propagated to providers, unlike
ag-agents): exposing gateway dispatch tools on a provider-propagated server
would let a provider surface recursively invoke the gateway that dispatches
back into providers — a re-entrancy and privilege-scope risk (RV20).
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents import agents_gateway_api as gateway
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

mcp = mcp_server(__name__)


def _mcp_capped(timeout_seconds: float | None) -> float:
    """Cap a blocking wait to what the MCP transport can hold.

    The client transport has its own 30-60s timeout, so an MCP tool call must
    never block indefinitely — it returns a 'running' status instead and the
    caller polls. This constraint belongs to the TRANSPORT, which is why it is
    applied here and not in the core gateway API: an in-process supervisor
    running a long implementation task has no such limit (RV511).
    """
    cap = gateway.MCP_BLOCKING_TIMEOUT_SECONDS
    return min(timeout_seconds, cap) if timeout_seconds else cap



@mcp.tool()
@log_tool_call
def agent_llm_submit(
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    timeout_seconds: float | None = None,
    fallback_profile_ids: list[str] | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit an async LLM gateway request. Returns immediately with request-id
    and initial state — use agent_llm_status/agent_llm_wait to check progress."""
    return gateway.submit_llm_request(
        project_root_from_env(),
        agent_profile_id=agent_profile_id,
        prompt_body=prompt_body,
        mode="async",
        timeout_seconds=timeout_seconds,
        fallback_profile_ids=fallback_profile_ids,
        source=source,
        metadata=metadata,
    )


@mcp.tool()
@log_tool_call
def agent_llm_status(request_id: str) -> dict[str, Any]:
    """Return the current persisted state of a gateway request."""
    return gateway.get_llm_request(project_root_from_env(), request_id)


@mcp.tool()
@log_tool_call
def agent_llm_wait(request_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Block until a request reaches a terminal state or timeout (capped for MCP transport)."""
    return gateway.wait_llm_request(
        project_root_from_env(), request_id, _mcp_capped(timeout_seconds)
    )


@mcp.tool()
@log_tool_call
def agent_llm_cancel(request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested."""
    return gateway.cancel_llm_request(project_root_from_env(), request_id)


@mcp.tool()
@log_tool_call
def agent_llm_run(
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    timeout_seconds: float | None = None,
    fallback_profile_ids: list[str] | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit and block until a terminal result or timeout. For one-shot use
    only — not for event-triggered paths (see AG12's async event surface)."""
    return gateway.run_llm_request(
        project_root_from_env(),
        agent_profile_id=agent_profile_id,
        prompt_body=prompt_body,
        timeout_seconds=_mcp_capped(timeout_seconds),
        fallback_profile_ids=fallback_profile_ids,
        source=source,
        metadata=metadata,
    )


@mcp.tool()
@log_tool_call
def agent_llm_list_requests(state: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """List persisted gateway requests, most recently created first.

    Optionally filter by state (queued/running/completed/failed/cancelled/
    rejected). Reads from disk, so this works even for requests from an
    earlier process — unlike queue depths, which are in-memory only.
    """
    return gateway.list_llm_requests(project_root_from_env(), state=state, limit=limit)


@mcp.tool()
@log_tool_call
def agent_llm_gateway_overview() -> dict[str, Any]:
    """Operator-facing summary: persisted request counts by state, the 5 most
    recent failures (with redacted error), and in-process per-profile queue depths."""
    return gateway.gateway_overview(project_root_from_env())


def main() -> None:
    run_mcp_server(mcp, "agents-gateway")


if __name__ == "__main__":
    main()
