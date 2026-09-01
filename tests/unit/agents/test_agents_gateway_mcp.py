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
        mock_call.return_value = {
            "task_id": "req_x",
            "lifecycle": "terminal",
            "activity_seq": 3,
            "activity_at": "2026-08-24T07:12:31Z",
            "outcome": "success",
        }
        result = agents_gateway_mcp.agent_task_status("req_x")
    assert result == mock_call.return_value
    mock_call.assert_called_once_with(
        "get_execution_request", _ROOT, "req_x"
    )


def test_agent_task_response_returns_small_verified_response_inline():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.side_effect = [
            "hello",
            {"request-id": "req_x", "state": "completed", "diagnostics": {}},
        ]
        result = agents_gateway_mcp.agent_task_response("req_x")

    assert result["delivery"] == "inline"
    assert result["text"] == "hello"
    assert result["bytes"] == 5
    assert mock_call.call_args_list[0].args == ("get_execution_response", _ROOT, "req_x")
    assert mock_call.call_args_list[1].args == ("get_execution_diagnostics", _ROOT, "req_x")
    assert mock_call.call_args_list[1].kwargs == {"limit": 1}


def test_agent_task_response_returns_large_response_without_a_path():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.side_effect = [
            "x" * 100_000,
            {
                "request-id": "req_x",
                "state": "failed",
                "diagnostics": {"failure-code": "EXT-ACP-TOOL-001"},
            },
        ]
        result = agents_gateway_mcp.agent_task_response("req_x")

    assert result["delivery"] == "inline"
    assert result["bytes"] == 100_000
    assert result["state"] == "failed"
    assert result["error-code"] == "EXT-ACP-TOOL-001"
    assert "artifact-path" not in result
    assert "response-artifact" not in result
    assert mock_call.call_args_list[0].args == ("get_execution_response", _ROOT, "req_x")


def test_agent_task_response_includes_provider_failure_code_with_full_output():
    with (
        _patch_root(),
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.side_effect = [
            "partial assistant output",
            {
                "request-id": "req_x",
                "state": "failed",
                "diagnostics": {
                    "failure-code": "EXT-ACP-TOOL-001",
                    "reason-code": "provider-cancelled-after-tool-failure",
                    "evidence": [{"tool": "not returned"}],
                },
            },
        ]
        result = agents_gateway_mcp.agent_task_response("req_x")

    assert result == {
        "request-id": "req_x",
        "delivery": "inline",
        "text": "partial assistant output",
        "bytes": len("partial assistant output".encode("utf-8")),
        "state": "failed",
        "error-code": "EXT-ACP-TOOL-001",
        "error-reason": "provider-cancelled-after-tool-failure",
    }


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
            "ses_old", "ctl_001", model_id="chatgpt"
        )
    assert result["session-id"] == "ses_new"
    mock_call.assert_called_once_with(
        "resume_execution_session",
        _ROOT,
        "ses_old",
        control_id="ctl_001",
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
        mock_call.return_value = [
            {
                "request-id": "req_x",
                "state": "completed",
                "output-preview": "must not cross MCP list",
                "output-truncated": True,
            }
        ]
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
        patch("audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method") as mock_call,
    ):
        mock_call.return_value = {
            "request-id": "req_x",
            "state": "queued",
        }
        result = agents_gateway_mcp.agent_task_submit("reviewer-agent", prompt_body="hi")

    assert result["state"] == "queued"
    mock_call.assert_called_once_with(
        "submit_execution_request",
        _ROOT,
        agent_id="reviewer-agent",
        prompt_body="hi",
        source=None,
        metadata=None,
        session_id=None,
        session_keep_alive=False,
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
            agents_gateway_mcp.agent_task_submit("missing-agent", prompt_body="test")

    # The domain error's code reaches the caller in the ToolError text, and
    # the original AudiaGenticError is preserved as the exception cause —
    # tool_boundary translates, it does not swallow.
    assert "RES-AGD-001" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, AudiaGenticError)
    assert excinfo.value.__cause__.code == "RES-AGD-001"
