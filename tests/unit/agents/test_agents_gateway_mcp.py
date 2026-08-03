"""Unit tests for agents_gateway_mcp — verify MCP tools delegate to agents_gateway_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents import agents_gateway_mcp

_ROOT = Path("/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.agents.agents_gateway_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_execution_submit_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_gateway_api.submit_execution_request",
        return_value={"request-id": "req_x", "state": "queued"},
    ) as mock:
        result = agents_gateway_mcp.agent_execution_submit(agent_profile_id="p", prompt_body="hi")
    assert result["state"] == "queued"
    mock.assert_called_once_with(
        _ROOT, agent_profile_id="p", prompt_body="hi", mode="async",
        timeout_seconds=None, source=None, metadata=None,
        session_id=None, session_keep_alive=False, session_idle_timeout_seconds=None,
        session_max_lifetime_seconds=None,
    )


def test_agent_execution_status_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_gateway_api.get_execution_request",
        return_value={"request-id": "req_x", "state": "completed"},
    ) as mock:
        result = agents_gateway_mcp.agent_execution_status("req_x")
    assert result["state"] == "completed"
    mock.assert_called_once_with(_ROOT, "req_x")


def test_agent_execution_wait_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_gateway_api.wait_execution_request",
        return_value={"request-id": "req_x", "state": "completed"},
    ) as mock:
        result = agents_gateway_mcp.agent_execution_wait("req_x", timeout_seconds=10)
    assert result["state"] == "completed"
    mock.assert_called_once_with(_ROOT, "req_x", 10)


def test_agent_execution_cancel_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_gateway_api.cancel_execution_request",
        return_value={"request-id": "req_x", "state": "cancelled"},
    ) as mock:
        result = agents_gateway_mcp.agent_execution_cancel("req_x")
    assert result["state"] == "cancelled"
    mock.assert_called_once_with(_ROOT, "req_x")


def test_agent_execution_run_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_gateway_api.run_execution_request",
        return_value={"request-id": "req_x", "state": "completed"},
    ) as mock:
        result = agents_gateway_mcp.agent_execution_run(agent_profile_id="p", prompt_body="hi")
    assert result["state"] == "completed"
    # The MCP boundary owns the transport cap and applies it before delegating;
    # the core gateway API honours whatever it is given, so an in-process
    # supervisor can wait out a long task (RV511).
    mock.assert_called_once_with(
        _ROOT, agent_profile_id="p", prompt_body="hi",
        timeout_seconds=agents_gateway_mcp.MCP_BLOCKING_TIMEOUT_SECONDS,
        source=None, metadata=None,
        session_id=None, session_keep_alive=False, session_idle_timeout_seconds=None,
        session_max_lifetime_seconds=None,
    )


def test_mcp_caps_a_long_requested_wait_but_core_api_does_not():
    """The 300s limit is an MCP transport constraint, not an execution limit."""
    # MCP boundary: a caller asking for an hour is capped to the transport limit.
    assert agents_gateway_mcp._mcp_capped(3600.0) == agents_gateway_mcp.MCP_BLOCKING_TIMEOUT_SECONDS
    assert agents_gateway_mcp._mcp_capped(None) == agents_gateway_mcp.MCP_BLOCKING_TIMEOUT_SECONDS
    # ...but a short request is honoured as-is.
    assert agents_gateway_mcp._mcp_capped(30.0) == 30.0


def test_agent_execution_list_requests_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_gateway_api.list_execution_requests",
        return_value=[{"request-id": "req_x", "state": "completed"}],
    ) as mock:
        result = agents_gateway_mcp.agent_execution_list_requests(state="completed", limit=5)
    assert result == [{"request-id": "req_x", "state": "completed"}]
    mock.assert_called_once_with(_ROOT, state="completed", limit=5)


def test_agent_execution_gateway_overview_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_gateway_api.gateway_overview",
        return_value={"total_requests": 3, "by_state": {"completed": 3}, "recent_failures": [], "queues": {}},
    ) as mock:
        result = agents_gateway_mcp.agent_execution_gateway_overview()
    assert result["total_requests"] == 3
    mock.assert_called_once_with(_ROOT)
