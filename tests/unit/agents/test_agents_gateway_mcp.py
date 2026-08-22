"""Unit tests for gateway_mcp — verify MCP tools delegate to gateway.api."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents.mcp import gateway_mcp as agents_gateway_mcp

_ROOT = Path("C:/fake/root")


def test_agent_task_list_definitions_is_a_registered_mcp_tool():
    """This tool previously existed on the module only as a plain, non-
    decorated function (agent_list_definitions) with a docstring saying
    'configuration MCP owns the public export.' A caller attached to ONLY
    the gateway server (this one) had no way to discover which agent_id
    values agent_task_submit would accept without also having the separate
    configuration server attached. Now registered here too (under its own
    name, since a tool name must have exactly one owning MCP surface), so
    gateway-only callers can self-discover valid agent_ids."""
    tools = asyncio.run(agents_gateway_mcp.mcp.list_tools())
    assert "agent_task_list_definitions" in {tool.name for tool in tools}


def _patch_root():
    return patch(
        "audiagentic.components.agents.mcp.gateway_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_task_list_definitions_returns_slim_client_facing_cards():
    """Modeled on the A2A AgentCard shape (protocols/a2a/agent_card.py):
    what an agent IS to a caller, never how it's implemented. Harness/
    wiring fields (execution_profile_id, role_ids, prompt_id, internal/
    acp/a2a flags) must not leak into this projection -- a calling agent
    has no use for them and must not couple to them."""
    raw = [
        {
            "agent_id": "gpt-auto-reviewer-agent",
            "name": "GPT-Auto Reviewer Agent",
            "prompt_id": "migrated-role-placeholder",
            "role_ids": ["reviewer"],
            "execution_profile_id": "gpt-auto",
            "description": "Real reviewer-role behavioral agent.",
            "advertised_skills": ["code-review"],
            "internal": True,
            "acp": False,
            "a2a": False,
        }
    ]
    with (
        _patch_root(),
        patch(
            "audiagentic.components.agents.configuration.global_catalog.list_global_agent_definitions",
            return_value=raw,
        ),
    ):
        result = agents_gateway_mcp.agent_task_list_definitions()

    assert result == [
        {
            "agent_id": "gpt-auto-reviewer-agent",
            "name": "GPT-Auto Reviewer Agent",
            "description": "Real reviewer-role behavioral agent.",
            "skills": [{"id": "code-review", "name": "code-review"}],
        }
    ]
    for leaked in ("prompt_id", "role_ids", "execution_profile_id", "internal", "acp", "a2a"):
        assert leaked not in result[0]


def test_agent_task_list_definitions_delegates():
    with (
        _patch_root(),
        patch(
            "audiagentic.components.agents.configuration.global_catalog.list_global_agent_definitions",
            return_value=[{"agent_id": "reviewer-agent"}],
        ) as mock_list,
    ):
        result = agents_gateway_mcp.agent_task_list_definitions()

    # name/description/skills are all absent on this bare fixture record and
    # _sparse strips absent values, so only agent_id survives.
    assert result == [{"agent_id": "reviewer-agent"}]
    mock_list.assert_called_once_with(_ROOT)


def test_agent_task_status_delegates():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = {"request-id": "req_x", "state": "completed"}
        result = agents_gateway_mcp.agent_task_status("req_x")
    assert result["state"] == "completed"
    mock_call.assert_called_once_with("get_execution_request", _ROOT, "req_x")


def test_agent_task_cancel_delegates():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = {"request-id": "req_x", "state": "cancelled"}
        result = agents_gateway_mcp.agent_task_cancel("req_x")
    assert result["state"] == "cancelled"
    mock_call.assert_called_once_with("cancel_execution_request", _ROOT, "req_x")


def test_agent_task_session_resume_delegates_to_gateway_client():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = {"session-id": "ses_new", "state": "active"}
        result = agents_gateway_mcp.agent_task_session_resume(
            "ses_old", "ctl_001", "identity", "execution", "chatgpt"
        )
    assert result["session-id"] == "ses_new"
    mock_call.assert_called_once_with(
        "resume_execution_session",
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
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = {"disposition": "accepted"}
        result = agents_gateway_mcp.agent_task_session_control(
            "ses_1", "cancel-turn", "ctl_1", turn_id="req_1"
        )
    assert result == {"disposition": "accepted"}
    mock_call.assert_called_once_with(
        "control_execution_session",
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
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = [{"request-id": "req_x", "state": "completed"}]
        result = agents_gateway_mcp.agent_task_list_requests(state="completed", limit=5)
    assert result == [{"request-id": "req_x", "state": "completed"}]
    mock_call.assert_called_once_with("list_execution_requests", _ROOT, state="completed", limit=5)


def test_agent_task_gateway_overview_delegates():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = {
            "total_requests": 3,
            "by_state": {"completed": 3},
            "recent_failures": [],
            "queues": {},
        }
        result = agents_gateway_mcp.agent_task_gateway_overview()
    assert result["total_requests"] == 3
    mock_call.assert_called_once_with("gateway_overview", _ROOT)


def test_agent_task_submit_resolves_agent_and_delegates():
    """agent_task_submit resolves the agent definition, then submits through
     the gateway client -- the sole MCP submission path (RV891)."""
    with (
        _patch_root(),
        patch(
            "audiagentic.components.agents.configuration.global_catalog.get_global_agent_definition",
            return_value={"agent_id": "reviewer-agent", "execution_profile_id": "fast"},
        ) as mock_get_definition,
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = {
            "request-id": "req_x",
            "state": "queued",
        }
        result = agents_gateway_mcp.agent_task_submit("reviewer-agent", prompt_body="hi")

    assert result["state"] == "queued"
    mock_get_definition.assert_called_once_with(_ROOT, "reviewer-agent")
    mock_call.assert_called_once_with(
        "submit_execution_request",
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
            "audiagentic.components.agents.configuration.global_catalog.get_global_agent_definition",
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
