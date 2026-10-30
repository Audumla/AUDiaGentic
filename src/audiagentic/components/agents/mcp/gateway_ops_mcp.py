"""Gateway operator MCP server: diagnostics, evidence, recovery and purge.

These tools are for an operator investigating or repairing gateway state, not
for agents that submit work, so they live apart from ``gateway_mcp`` and are
installed only on request (``propagate: none`` keeps ``audiagentic setup``
from registering them).
"""

from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.client import call_gateway_method
from audiagentic.components.agents.gateway.evidence_projection import project_public_gateway_request
from audiagentic.components.agents.mcp.gateway_mcp_support import (
    _page_limit,
    _request_project_root,
    _sparse,
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
def agent_task_diagnostics(request_id: str, limit: int = 25) -> dict[str, Any]:
    """Return bounded, redacted failure and activity evidence for a request."""
    project_root = _request_project_root(request_id)
    _page_limit(limit)
    return _sparse(
        call_gateway_method(
            "get_execution_diagnostics", project_root, request_id=request_id, limit=limit
        )
    )


@mcp.tool()
@tool_boundary
def agent_task_observations(
    request_id: str,
    limit: int = 25,
    cursor: str | None = None,
    since_sequence: int | None = None,
    tail: int | None = None,
) -> dict[str, Any]:
    """Read bounded DOM/activity and node-stage evidence across retained segments.

    Eligible raw traces expire after five days by default; protected request
    evidence is retained longer. Node milestones are not native completion;
    request outcome and final output are separate.
    """
    project_root = _request_project_root(request_id)
    _page_limit(limit)
    params: dict[str, Any] = {
        "limit": limit,
        "cursor": cursor,
        "since_sequence": since_sequence,
    }
    if tail is not None:
        params["tail"] = tail
    return _sparse(
        call_gateway_method(
            "get_execution_observations",
            project_root,
            request_id,
            **params,
        )
    )


@mcp.tool()
@tool_boundary
def agent_task_evidence(
    request_id: str,
    include_observations: bool = False,
    include_history: bool = False,
    include_recovery: bool = False,
    limit: int = 25,
    cursor: str | None = None,
    observation_cursor: str | None = None,
    recovery_cursor: str | None = None,
    history_cursor: str | None = None,
    since_sequence: int | None = None,
) -> dict[str, Any]:
    """Return compact evidence; observation/history/recovery tiers are opt-in."""
    project_root = _request_project_root(request_id)
    _page_limit(limit)
    params: dict[str, Any] = {
        "include_observations": include_observations,
        "include_history": include_history,
        "include_recovery": include_recovery,
        "limit": limit,
        "cursor": cursor,
        "since_sequence": since_sequence,
    }
    if observation_cursor is not None:
        params["observation_cursor"] = observation_cursor
    if recovery_cursor is not None:
        params["recovery_cursor"] = recovery_cursor
    if history_cursor is not None:
        params["history_cursor"] = history_cursor
    raw = call_gateway_method(
            "get_execution_evidence",
            project_root,
            request_id,
            **params,
        )
    from audiagentic.components.agents.gateway.evidence_projection import (
        project_public_gateway_evidence,
    )
    return _sparse(project_public_gateway_evidence(raw))

@mcp.tool()
@tool_boundary
def agent_task_observation_replay(request_id: str) -> dict[str, Any]:
    """Replay request-owned observations into a compact recovery analysis."""
    project_root = _request_project_root(request_id)
    return _sparse(
        call_gateway_method(
            "replay_execution_observations",
            project_root,
            request_id,
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
    project_root = _request_project_root(request_id)
    return project_public_gateway_request(
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
def agent_task_failure_response(request_id: str) -> dict[str, Any]:
    """Return provider text captured as diagnostic evidence on a failed request."""
    project_root = _request_project_root(request_id)
    text = call_gateway_method("get_execution_failure_response", project_root, request_id)
    return {
        "request-id": request_id,
        "delivery": "inline",
        "classification": "failure-diagnostic",
        "text": text,
        "bytes": len(text.encode("utf-8")),
    }


@mcp.tool()
@tool_boundary
def agent_task_complete_from_provider(request_id: str) -> dict[str, Any]:
    """Capture the request-owned current provider response and mark it completed; never send a prompt."""
    project_root = _request_project_root(request_id)
    return project_public_gateway_request(call_gateway_method("complete_execution_from_provider", project_root, request_id))


@mcp.tool()
@tool_boundary
def agent_task_gateway_overview() -> dict[str, Any]:
    """Return request counts, recent redacted failures, and provider activity."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("gateway_overview", project_root))


@mcp.tool()
@tool_boundary
def agent_task_session_purge(session_id: str) -> dict[str, Any]:
    """Permanently purge one terminal gateway session and its request data."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("purge_execution_session", project_root, session_id))


@mcp.tool()
@tool_boundary
def agent_task_gateway_purge(
    dry_run: bool = True,
    session_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect or purge terminal gateway sessions; dry-run defaults to true."""
    project_root = project_root_from_env()
    return _sparse(
        call_gateway_method(
            "purge_execution_sessions",
            project_root,
            dry_run=dry_run,
            session_ids=session_ids,
        )
    )


def main() -> None:
    run_mcp_server(mcp, "agents-gateway-ops")


if __name__ == "__main__":
    main()
