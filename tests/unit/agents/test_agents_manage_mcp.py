"""Unit tests for the registered config and admin MCP surfaces."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from audiagentic.components.agents.mcp import admin_mcp, config_mcp

_ROOT = Path("/fake/root")


@contextmanager
def _patch_roots():
    with patch("audiagentic.components.agents.mcp.config_mcp.project_root_from_env", return_value=_ROOT), patch(
        "audiagentic.components.agents.mcp.admin_mcp.project_root_from_env", return_value=_ROOT
    ):
        yield


def test_agent_list_execution_profiles_delegates_to_api():
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.execution_profile_api.list_execution_profiles",
        return_value=[{"profile_id": "default"}],
    ) as mock:
        result = config_mcp.agent_list_execution_profiles()
    assert result == [{"profile_id": "default"}]
    mock.assert_called_once_with(_ROOT)


def test_agent_get_execution_profile_delegates_to_api():
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.execution_profile_api.get_execution_profile",
        return_value={"profile_id": "test"},
    ) as mock:
        result = config_mcp.agent_get_execution_profile("test")
    assert result == {"profile_id": "test"}
    mock.assert_called_once_with(_ROOT, "test")


def test_agent_create_execution_profile_delegates_to_api():
    profile = {"profile_id": "new", "provider_id": "openai", "model_id": "gpt-4o"}
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.execution_profile_api.create_execution_profile",
        return_value=profile,
    ) as mock:
        result = config_mcp.agent_create_execution_profile(profile)
    assert result == profile
    mock.assert_called_once_with(_ROOT, profile)


def test_agent_update_execution_profile_delegates_to_api():
    updates = {"model_id": "gpt-4o-mini"}
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.execution_profile_api.update_execution_profile",
        return_value={"profile_id": "test", "model_id": "gpt-4o-mini"},
    ) as mock:
        result = config_mcp.agent_update_execution_profile("test", updates)
    assert result["model_id"] == "gpt-4o-mini"
    mock.assert_called_once_with(_ROOT, "test", updates)


def test_agent_delete_execution_profile_delegates_to_api():
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.execution_profile_api.delete_execution_profile",
        return_value={"profile_id": "test"},
    ) as mock:
        result = config_mcp.agent_delete_execution_profile("test")
    assert result == {"profile_id": "test"}
    mock.assert_called_once_with(_ROOT, "test")


def test_agent_list_roles_delegates_to_api():
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.role_api.list_roles",
        return_value=[{"role_id": "reviewer"}],
    ) as mock:
        result = config_mcp.agent_list_roles()
    assert result == [{"role_id": "reviewer"}]
    mock.assert_called_once_with(_ROOT)


def test_agent_get_role_delegates_to_api():
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.role_api.get_role",
        return_value={"role_id": "reviewer"},
    ) as mock:
        result = config_mcp.agent_get_role("reviewer")
    assert result == {"role_id": "reviewer"}
    mock.assert_called_once_with(_ROOT, "reviewer")


def test_agent_create_role_delegates_to_api():
    role = {"role_id": "reviewer", "instructions": "Review."}
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.role_api.create_role",
        return_value=role,
    ) as mock:
        result = config_mcp.agent_create_role(role)
    assert result == role
    mock.assert_called_once_with(_ROOT, role)


def test_agent_update_role_delegates_to_api():
    updates = {"instructions": "Updated."}
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.role_api.update_role",
        return_value={"role_id": "reviewer", "instructions": "Updated."},
    ) as mock:
        result = config_mcp.agent_update_role("reviewer", updates)
    assert result["instructions"] == "Updated."
    mock.assert_called_once_with(_ROOT, "reviewer", updates)


def test_agent_delete_role_delegates_to_api():
    with _patch_roots(), patch(
        "audiagentic.components.agents.models.role_api.delete_role",
        return_value={"role_id": "reviewer"},
    ) as mock:
        result = config_mcp.agent_delete_role("reviewer")
    assert result == {"role_id": "reviewer"}
    mock.assert_called_once_with(_ROOT, "reviewer")


def test_gateway_operation_mcp_tools_delegate_to_management_api():
    with _patch_roots(), patch(
        "audiagentic.components.agents.gateway.management_api.gateway_create_operation",
        return_value={"operation-id": "op_001", "state": "accepted"},
    ) as create, patch(
        "audiagentic.components.agents.gateway.management_api.gateway_get_operation",
        return_value={"operation-id": "op_001", "state": "completed"},
    ) as get:
        created = admin_mcp.agent_gateway_create_operation(
            "op_001", "reconcile", {"project-root": "C:/workspace"}, "corr_1"
        )
        current = admin_mcp.agent_gateway_get_operation("op_001")

    assert created["state"] == "accepted"
    assert current["state"] == "completed"
    create.assert_called_once_with(
        _ROOT,
        operation_id="op_001",
        kind="reconcile",
        scope={"project-root": "C:/workspace"},
        correlation_id="corr_1",
    )
    get.assert_called_once_with(_ROOT, "op_001")


def test_gateway_retention_policy_mcp_tool_delegates_to_management_api():
    expected = {
        "available": True,
        "purge-enabled": False,
        "minimum-archive-age-seconds": 0.0,
        "max-batch-size": 100,
        "policy-id": "machine-default",
        "policy-digest": "abc",
    }
    with _patch_roots(), patch(
        "audiagentic.components.agents.gateway.management_api.gateway_get_retention_policy",
        return_value=expected,
    ) as mock:
        result = admin_mcp.agent_gateway_get_retention_policy()
    assert result == expected
    mock.assert_called_once_with(_ROOT)
