"""Unit tests for agents_manage_mcp — verify MCP tools delegate to agents_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents import agents_manage_mcp

_ROOT = Path("/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.agents.agents_manage_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_list_profiles_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.list_profiles",
        return_value=[{"profile_id": "default"}],
    ) as mock:
        result = agents_manage_mcp.agent_list_profiles()
    assert result == [{"profile_id": "default"}]
    mock.assert_called_once_with(_ROOT)


def test_agent_get_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.get_profile",
        return_value={"profile_id": "test"},
    ) as mock:
        result = agents_manage_mcp.agent_get_profile("test")
    assert result == {"profile_id": "test"}
    mock.assert_called_once_with(_ROOT, "test")


def test_agent_create_profile_delegates_to_api():
    profile = {"profile_id": "new", "provider_id": "openai", "model_id": "gpt-4o"}
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.create_profile",
        return_value=profile,
    ) as mock:
        result = agents_manage_mcp.agent_create_profile(profile)
    assert result == profile
    mock.assert_called_once_with(_ROOT, profile)


def test_agent_update_profile_delegates_to_api():
    updates = {"model_id": "gpt-4o-mini"}
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.update_profile",
        return_value={"profile_id": "test", "model_id": "gpt-4o-mini"},
    ) as mock:
        result = agents_manage_mcp.agent_update_profile("test", updates)
    assert result["model_id"] == "gpt-4o-mini"
    mock.assert_called_once_with(_ROOT, "test", updates)


def test_agent_delete_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.agents_api.delete_profile",
        return_value={"profile_id": "test"},
    ) as mock:
        result = agents_manage_mcp.agent_delete_profile("test")
    assert result == {"profile_id": "test"}
    mock.assert_called_once_with(_ROOT, "test")
