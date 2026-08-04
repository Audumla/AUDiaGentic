"""Unit tests for agents_manage_mcp — verify MCP tools delegate to agents_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents.mcp import manage_mcp as agents_manage_mcp

_ROOT = Path("/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.agents.mcp.manage_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_agent_list_execution_profiles_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.list_execution_profiles",
        return_value=[{"profile_id": "default"}],
    ) as mock:
        result = agents_manage_mcp.agent_list_execution_profiles()
    assert result == [{"profile_id": "default"}]
    mock.assert_called_once_with(_ROOT)


def test_agent_get_execution_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.get_execution_profile",
        return_value={"profile_id": "test"},
    ) as mock:
        result = agents_manage_mcp.agent_get_execution_profile("test")
    assert result == {"profile_id": "test"}
    mock.assert_called_once_with(_ROOT, "test")


def test_agent_create_execution_profile_delegates_to_api():
    profile = {"profile_id": "new", "provider_id": "openai", "model_id": "gpt-4o"}
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.create_execution_profile",
        return_value=profile,
    ) as mock:
        result = agents_manage_mcp.agent_create_execution_profile(profile)
    assert result == profile
    mock.assert_called_once_with(_ROOT, profile)


def test_agent_update_execution_profile_delegates_to_api():
    updates = {"model_id": "gpt-4o-mini"}
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.update_execution_profile",
        return_value={"profile_id": "test", "model_id": "gpt-4o-mini"},
    ) as mock:
        result = agents_manage_mcp.agent_update_execution_profile("test", updates)
    assert result["model_id"] == "gpt-4o-mini"
    mock.assert_called_once_with(_ROOT, "test", updates)


def test_agent_delete_execution_profile_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.execution_profile_api.delete_execution_profile",
        return_value={"profile_id": "test"},
    ) as mock:
        result = agents_manage_mcp.agent_delete_execution_profile("test")
    assert result == {"profile_id": "test"}
    mock.assert_called_once_with(_ROOT, "test")


def test_agent_list_roles_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.role_api.list_roles",
        return_value=[{"role_id": "reviewer"}],
    ) as mock:
        result = agents_manage_mcp.agent_list_roles()
    assert result == [{"role_id": "reviewer"}]
    mock.assert_called_once_with(_ROOT)


def test_agent_get_role_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.role_api.get_role",
        return_value={"role_id": "reviewer"},
    ) as mock:
        result = agents_manage_mcp.agent_get_role("reviewer")
    assert result == {"role_id": "reviewer"}
    mock.assert_called_once_with(_ROOT, "reviewer")


def test_agent_create_role_delegates_to_api():
    role = {"role_id": "reviewer", "instructions": "Review."}
    with _patch_root(), patch(
        "audiagentic.components.agents.models.role_api.create_role",
        return_value=role,
    ) as mock:
        result = agents_manage_mcp.agent_create_role(role)
    assert result == role
    mock.assert_called_once_with(_ROOT, role)


def test_agent_update_role_delegates_to_api():
    updates = {"instructions": "Updated."}
    with _patch_root(), patch(
        "audiagentic.components.agents.models.role_api.update_role",
        return_value={"role_id": "reviewer", "instructions": "Updated."},
    ) as mock:
        result = agents_manage_mcp.agent_update_role("reviewer", updates)
    assert result["instructions"] == "Updated."
    mock.assert_called_once_with(_ROOT, "reviewer", updates)


def test_agent_delete_role_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.agents.models.role_api.delete_role",
        return_value={"role_id": "reviewer"},
    ) as mock:
        result = agents_manage_mcp.agent_delete_role("reviewer")
    assert result == {"role_id": "reviewer"}
    mock.assert_called_once_with(_ROOT, "reviewer")
