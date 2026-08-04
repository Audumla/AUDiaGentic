"""Unit tests for agents_mcp — verify MCP tools delegate to agents_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents.mcp import resolve_mcp as agents_mcp

_ROOT = Path("/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.agents.mcp.resolve_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_resolve_execution_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.resolve_execution_profile",
        return_value={"profile_id": "test", "provider_id": "openai", "model_id": "gpt-4o"},
    ) as mock:
        result = agents_mcp.agent_resolve_execution_profile("test")
    assert result["provider_id"] == "openai"
    assert result["model_id"] == "gpt-4o"
    mock.assert_called_once_with(_ROOT, "test")


def test_agent_resolve_default_execution_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.resolve_default_execution_profile",
        return_value={"profile_id": "default", "provider_id": "openai", "model_id": "gpt-4o"},
    ) as mock:
        result = agents_mcp.agent_resolve_default_execution_profile()
    assert result["profile_id"] == "default"
    mock.assert_called_once_with(_ROOT)


def test_agent_list_execution_profiles_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.list_execution_profiles",
        return_value=[{"profile_id": "a"}, {"profile_id": "b"}],
    ) as mock:
        result = agents_mcp.agent_list_execution_profiles()
    assert len(result) == 2
    mock.assert_called_once_with(_ROOT)
