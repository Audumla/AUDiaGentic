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
    resolve_request_project_root,
    resolve_session_project_root,
)
from audiagentic.components.agents.gateway.evidence_projection import (
    project_public_gateway_request,
    project_public_gateway_session,
)
from audiagentic.components.agents.gateway.evidence_projection import (
    public_gateway_scalar as _public_scalar,
)
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__, structured_output_only=True)

_RESPONSE_PREVIEW_FIELDS = frozenset({"output-preview", "output-truncated"})

_MAX_PAGE = 100


def _request_project_root(request_id: str):
    return resolve_request_project_root(project_root_from_env(), request_id)


def _session_project_root(session_id: str):
    return resolve_session_project_root(project_root_from_env(), session_id)


def _page_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_PAGE:
        raise ValueError(f"limit must be an integer between 1 and {_MAX_PAGE}")
    return value

def _status_without_response_preview(status: dict[str, Any], *, include_response: bool = False) -> dict[str, Any]:
    """Keep MCP status compact and null-free; never spend tokens on a preview."""
    allowed = {"task_id", "request_id", "request-id", "session_id", "session-id", "lifecycle", "state", "activity_seq", "activity-seq", "activity_at", "activity-at", "activity", "activity_type", "outcome", "error_code", "error-code", "contract-version", "revision"}
    result = {key: _public_scalar(status.get(key)) for key in allowed if key not in _RESPONSE_PREVIEW_FIELDS and _public_scalar(status.get(key)) is not None}
    session_id = status.get("session_id") or status.get("session-id")
    if isinstance(session_id, str) and session_id:
        result["session_id"] = session_id
    if include_response and isinstance(status.get("response"), dict):
        response = status["response"]
        result["response"] = {
            key: _public_scalar(response.get(key))
            for key in ("text", "bytes", "format", "media_type")
            if _public_scalar(response.get(key)) is not None
        }
    return result


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
    """Read a bounded page across retained daily plain/gzip observations.

    Eligible raw traces expire after five days by default; protected request
    evidence is retained longer. Request outcome and final output are separate.
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
def agent_task_gateway_overview() -> dict[str, Any]:
    """Return request counts, recent redacted failures, and provider activity."""
    project_root = project_root_from_env()
    return _sparse(call_gateway_method("gateway_overview", project_root))


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
    return project_public_gateway_request(status)


def main() -> None:
    run_mcp_server(mcp, "agents-gateway")


if __name__ == "__main__":
    main()
