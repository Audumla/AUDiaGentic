"""Unit tests for gateway_mcp — verify MCP tools delegate to gateway.api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents.mcp import gateway_mcp as agents_gateway_mcp

_ROOT = Path("/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.agents.mcp.gateway_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_task_status_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client"
    ) as mock_get:
        mock = mock_get.return_value
        mock.get_execution_request.return_value = {"request-id": "req_x", "state": "completed"}
        result = agents_gateway_mcp.agent_task_status("req_x")
    assert result["state"] == "completed"
    mock.get_execution_request.assert_called_once_with(_ROOT, "req_x")


def test_agent_task_wait_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client"
    ) as mock_get:
        mock = mock_get.return_value
        mock.wait_execution_request.return_value = {"request-id": "req_x", "state": "completed"}
        result = agents_gateway_mcp.agent_task_wait("req_x", timeout_seconds=10)
    assert result["state"] == "completed"
    mock.wait_execution_request.assert_called_once_with(_ROOT, "req_x", 10)


def test_agent_task_cancel_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client"
    ) as mock_get:
        mock = mock_get.return_value
        mock.cancel_execution_request.return_value = {"request-id": "req_x", "state": "cancelled"}
        result = agents_gateway_mcp.agent_task_cancel("req_x")
    assert result["state"] == "cancelled"
    mock.cancel_execution_request.assert_called_once_with(_ROOT, "req_x")


def test_mcp_caps_a_long_requested_wait_but_core_api_does_not():
    """The 300s limit is an MCP transport constraint, not an execution limit."""
    # MCP boundary: a caller asking for an hour is capped to the transport limit.
    assert agents_gateway_mcp._mcp_capped(3600.0) == agents_gateway_mcp.MCP_BLOCKING_TIMEOUT_SECONDS
    assert agents_gateway_mcp._mcp_capped(None) == agents_gateway_mcp.MCP_BLOCKING_TIMEOUT_SECONDS
    # ...but a short request is honoured as-is.
    assert agents_gateway_mcp._mcp_capped(30.0) == 30.0


def test_agent_task_list_requests_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client"
    ) as mock_get:
        mock = mock_get.return_value
        mock.list_execution_requests.return_value = [{"request-id": "req_x", "state": "completed"}]
        result = agents_gateway_mcp.agent_task_list_requests(state="completed", limit=5)
    assert result == [{"request-id": "req_x", "state": "completed"}]
    mock.list_execution_requests.assert_called_once_with(_ROOT, state="completed", limit=5)


def test_agent_task_gateway_overview_delegates():
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client"
    ) as mock_get:
        mock = mock_get.return_value
        mock.gateway_overview.return_value = {"total_requests": 3, "by_state": {"completed": 3}, "recent_failures": [], "queues": {}}
        result = agents_gateway_mcp.agent_task_gateway_overview()
    assert result["total_requests"] == 3
    mock.gateway_overview.assert_called_once_with(_ROOT)


def test_agent_task_submit_resolves_agent_and_delegates():
    """agent_task_submit resolves the agent definition, then submits through
    the gateway client -- the sole MCP submission path (RV891). Returns
    task.status(): a delegating re-read through the same client, not the raw
    submit response -- so both client calls are mocked."""
    with _patch_root(), patch(
        "audiagentic.components.agents.models.agent_definition_api.get_agent_definition",
        return_value={"agent_id": "reviewer-agent", "execution_profile_id": "fast"},
    ) as mock_get_definition, patch(
        "audiagentic.components.agents.gateway.client.get_gateway_client"
    ) as mock_get_client:
        mock_client = mock_get_client.return_value
        mock_client.submit_execution_request.return_value = {
            "request-id": "req_x",
            "state": "queued",
        }
        mock_client.get_execution_request.return_value = {
            "request-id": "req_x",
            "state": "queued",
        }
        result = agents_gateway_mcp.agent_task_submit("reviewer-agent", prompt_body="hi")

    assert result["state"] == "queued"
    mock_get_definition.assert_called_once_with(_ROOT, "reviewer-agent")
    mock_client.get_execution_request.assert_called_once_with(_ROOT, "req_x")
    mock_client.submit_execution_request.assert_called_once_with(
        _ROOT,
        execution_profile_id="fast",
        prompt_body="hi",
        timeout_seconds=None,
        source=None,
        metadata=None,
        session_id=None,
        session_keep_alive=False,
        session_idle_timeout_seconds=None,
        session_max_lifetime_seconds=None,
    )


def test_agent_task_submit_unknown_agent_propagates_error():
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    with _patch_root(), patch(
        "audiagentic.components.agents.models.agent_definition_api.get_agent_definition",
        side_effect=AudiaGenticError(
            code="RES-AGD-001", kind="agents", message="not found", details={}
        ),
    ):
        try:
            agents_gateway_mcp.agent_task_submit("missing-agent")
        except AudiaGenticError as exc:
            assert exc.code == "RES-AGD-001"
        else:
            raise AssertionError("expected AudiaGenticError")
