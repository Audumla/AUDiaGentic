from __future__ import annotations

import asyncio
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents.mcp import gateway_mcp, gateway_ops_mcp

_ROOT = Path("C:/fake/root")


def _patch_root():
    stack = ExitStack()
    for module in ("gateway_mcp", "gateway_ops_mcp", "gateway_mcp_support"):
        stack.enter_context(
            patch(f"audiagentic.components.agents.mcp.{module}.project_root_from_env", return_value=_ROOT)
        )
    return stack


def test_observations_tool_is_explicit_and_cursor_based():
    payload = {"items": [{"event_seq": 1}], "count": 1, "has_more": False}
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_ops_mcp.call_gateway_method",
        return_value=payload,
    ) as call:
        result = gateway_ops_mcp.agent_task_observations(
            "req-1", limit=10, cursor="opaque", since_sequence=3
        )
    assert result == payload
    call.assert_called_once_with(
        "get_execution_observations",
        _ROOT,
        "req-1",
        limit=10,
        cursor="opaque",
        since_sequence=3,
    )


def test_evidence_is_compact_by_default_and_detail_is_opt_in():
    payload = {
        "schema_version": "gateway-evidence.v1",
        "request-id": "req-1",
        "state": "running",
        "diagnostics": {"classification": "watchdog"},
    }
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_ops_mcp.call_gateway_method",
        return_value=payload,
    ) as call:
        result = gateway_ops_mcp.agent_task_evidence("req-1")
    assert result == payload
    call.assert_called_once_with(
        "get_execution_evidence",
        _ROOT,
        "req-1",
        include_observations=False,
        include_history=False,
        include_recovery=False,
        limit=25,
        cursor=None,
        since_sequence=None,
    )


def test_evidence_uses_independent_observation_and_recovery_cursors():
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_ops_mcp.call_gateway_method",
        return_value={},
    ) as call:
        gateway_ops_mcp.agent_task_evidence(
            "req-1",
            include_observations=True,
            include_recovery=True,
            cursor="shared",
            observation_cursor="obs",
            recovery_cursor="recovery",
        )
    call.assert_called_once_with(
        "get_execution_evidence",
        _ROOT,
        "req-1",
        include_observations=True,
        include_history=False,
        include_recovery=True,
        limit=25,
        cursor="shared",
        observation_cursor="obs",
        recovery_cursor="recovery",
        since_sequence=None,
    )

def test_observation_replay_is_read_only_and_explicit():
    payload = {
        "request-id": "req-1",
        "safe-to-resubmit": False,
        "duplicate-prompt-fence": "no-automatic-resubmit",
    }
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_ops_mcp.call_gateway_method",
        return_value=payload,
    ) as call:
        result = gateway_ops_mcp.agent_task_observation_replay("req-1")
    assert result == payload
    call.assert_called_once_with(
        "replay_execution_observations",
        _ROOT,
        "req-1",
    )


def test_new_tools_are_registered_once():
    tools = asyncio.run(gateway_ops_mcp.mcp.list_tools())
    names = [tool.name for tool in tools]
    assert not {n for n in names} & {t.name for t in asyncio.run(gateway_mcp.mcp.list_tools())}
    assert names.count("agent_task_observations") == 1
    assert names.count("agent_task_evidence") == 1
    assert names.count("agent_task_observation_replay") == 1


def test_request_list_has_finite_default_limit():
    with _patch_root(), patch(
        "audiagentic.components.agents.mcp.gateway_mcp.call_gateway_method",
        return_value=[],
    ) as call:
        assert gateway_mcp.agent_task_list_requests() == []
    call.assert_called_once_with(
        "list_execution_requests",
        _ROOT,
        state=None,
        limit=25,
    )