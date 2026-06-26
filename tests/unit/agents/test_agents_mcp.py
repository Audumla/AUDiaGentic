"""Unit tests for agents_mcp — verify MCP tools delegate to agents_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents import agents_mcp

_ROOT = Path("/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.agents.agents_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_resolve_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.resolve_profile",
        return_value={"profile_id": "test", "provider_id": "openai", "model_id": "gpt-4o"},
    ) as mock:
        result = agents_mcp.agent_resolve_profile("test")
    assert result["provider_id"] == "openai"
    assert result["model_id"] == "gpt-4o"
    mock.assert_called_once_with(_ROOT, "test")


def test_agent_resolve_default_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.resolve_default_profile",
        return_value={"profile_id": "default", "provider_id": "openai", "model_id": "gpt-4o"},
    ) as mock:
        result = agents_mcp.agent_resolve_default_profile()
    assert result["profile_id"] == "default"
    mock.assert_called_once_with(_ROOT)


def test_agent_list_profiles_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.list_profiles",
        return_value=[{"profile_id": "a"}, {"profile_id": "b"}],
    ) as mock:
        result = agents_mcp.agent_list_profiles()
    assert len(result) == 2
    mock.assert_called_once_with(_ROOT)
