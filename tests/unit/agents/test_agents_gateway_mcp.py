"""Unit tests for gateway_mcp — verify MCP tools delegate to gateway.api."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents.mcp import gateway_mcp as agents_gateway_mcp

_ROOT = Path("C:/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.agents.mcp.gateway_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_list_definitions_delegates():
    with (
        _patch_root(),
        patch(
            "audiagentic.components.agents.models.agent_definition_api.list_agent_definitions",
            return_value=[{"agent_id": "reviewer-agent"}],
        ) as mock_list,
    ):
        result = agents_gateway_mcp.agent_list_definitions()

    assert result == [{"agent_id": "reviewer-agent"}]
    mock_list.assert_called_once_with(_ROOT)


def test_agent_task_status_delegates():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client") as mock_get,
    ):
        mock = mock_get.return_value
        mock.get_execution_request.return_value = {"request-id": "req_x", "state": "completed"}
        result = agents_gateway_mcp.agent_task_status("req_x")
    assert result["state"] == "completed"
    mock_get.assert_called_once_with(_ROOT)
    mock.get_execution_request.assert_called_once_with(_ROOT, "req_x")


def test_agent_task_cancel_delegates():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client") as mock_get,
    ):
        mock = mock_get.return_value
        mock.cancel_execution_request.return_value = {"request-id": "req_x", "state": "cancelled"}
        result = agents_gateway_mcp.agent_task_cancel("req_x")
    assert result["state"] == "cancelled"
    mock_get.assert_called_once_with(_ROOT)
    mock.cancel_execution_request.assert_called_once_with(_ROOT, "req_x")


def test_agent_task_session_resume_delegates_to_gateway_client():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client") as mock_get,
    ):
        mock = mock_get.return_value
        mock.resume_execution_session.return_value = {"session-id": "ses_new", "state": "active"}
        result = agents_gateway_mcp.agent_task_session_resume(
            "ses_old", "ctl_001", "identity", "execution", "chatgpt"
        )
    assert result["session-id"] == "ses_new"
    mock.resume_execution_session.assert_called_once_with(
        _ROOT,
        "ses_old",
        control_id="ctl_001",
        identity_context_fingerprint="identity",
        execution_context_fingerprint="execution",
        model_id="chatgpt",
    )


def test_agent_task_session_control_delegates_to_gateway_client():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client") as mock_get,
    ):
        mock = mock_get.return_value
        mock.control_execution_session.return_value = {"disposition": "accepted"}
        result = agents_gateway_mcp.agent_task_session_control(
            "ses_1", "cancel-turn", "ctl_1", turn_id="req_1"
        )
    assert result == {"disposition": "accepted"}
    mock.control_execution_session.assert_called_once_with(
        _ROOT,
        "ses_1",
        action="cancel-turn",
        control_id="ctl_1",
        turn_id="req_1",
        payload=None,
    )


def test_agent_task_list_requests_delegates():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client") as mock_get,
    ):
        mock = mock_get.return_value
        mock.list_execution_requests.return_value = [{"request-id": "req_x", "state": "completed"}]
        result = agents_gateway_mcp.agent_task_list_requests(state="completed", limit=5)
    assert result == [{"request-id": "req_x", "state": "completed"}]
    mock_get.assert_called_once_with(_ROOT)
    mock.list_execution_requests.assert_called_once_with(_ROOT, state="completed", limit=5)


def test_agent_task_gateway_overview_delegates():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client") as mock_get,
    ):
        mock = mock_get.return_value
        mock.gateway_overview.return_value = {
            "total_requests": 3,
            "by_state": {"completed": 3},
            "recent_failures": [],
            "queues": {},
        }
        result = agents_gateway_mcp.agent_task_gateway_overview()
    assert result["total_requests"] == 3
    mock_get.assert_called_once_with(_ROOT)
    mock.gateway_overview.assert_called_once_with(_ROOT)


def test_agent_task_submit_resolves_agent_and_delegates():
    """agent_task_submit resolves the agent definition, then submits through
     the gateway client -- the sole MCP submission path (RV891)."""
    with (
        _patch_root(),
        patch(
            "audiagentic.components.agents.models.agent_definition_api.get_agent_definition",
            return_value={"agent_id": "reviewer-agent", "execution_profile_id": "fast"},
        ) as mock_get_definition,
        patch("audiagentic.components.agents.mcp.gateway_mcp.get_gateway_client") as mock_get_client,
    ):
        mock_client = mock_get_client.return_value
        mock_client.submit_execution_request.return_value = {
            "request-id": "req_x",
            "state": "queued",
        }
        result = agents_gateway_mcp.agent_task_submit("reviewer-agent", prompt_body="hi")

    assert result["state"] == "queued"
    mock_get_definition.assert_called_once_with(_ROOT, "reviewer-agent")
    mock_client.get_execution_request.assert_not_called()
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
    import pytest

    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.mcp.component_server import ToolError

    with (
        _patch_root(),
        patch(
            "audiagentic.components.agents.models.agent_definition_api.get_agent_definition",
            side_effect=AudiaGenticError(
                code="RES-AGD-001", kind="agents", message="not found", details={}
            ),
        ),
    ):
        with pytest.raises(ToolError) as excinfo:
            agents_gateway_mcp.agent_task_submit("missing-agent")

    # The domain error's code reaches the caller in the ToolError text, and
    # the original AudiaGenticError is preserved as the exception cause —
    # tool_boundary translates, it does not swallow.
    assert "RES-AGD-001" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, AudiaGenticError)
    assert excinfo.value.__cause__.code == "RES-AGD-001"
