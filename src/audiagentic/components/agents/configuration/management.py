"""Canonical CRUD operations for the machine-global Agents catalog.

This module is the management boundary for roles, execution profiles, and
agent definitions.  It deliberately works through ``AgentsConfigRepository``
and never selects a project-local authority.  The old ``*_api`` modules are
being retired under SU02; callers should import these functions instead.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.models.agent_definition import (
    AgentDefinitionStore,
    agent_definition_from_dict,
    agent_definition_to_dict,
)
from audiagentic.components.agents.models.execution_profile import (
    ExecutionProfileStore,
    execution_profile_from_dict,
    execution_profile_to_dict,
)
from audiagentic.components.agents.models.role import RoleStore, role_from_dict, role_to_dict
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .contracts import AgentsConfigDocument
from .repository import AgentsConfigRepository


def _repository() -> AgentsConfigRepository:
    return AgentsConfigRepository(global_agents_config_path(), required=True)


def _read(project_root: Path):
    return _repository().read(project_root)


def _replace_collection(
    project_root: Path,
    *,
    collection: str,
    values: tuple[dict[str, Any], ...],
) -> None:
    repository = _repository()
    snapshot = repository.read(project_root)
    fields: dict[str, Any] = {
        "prompts": snapshot.document.prompts,
        "roles": snapshot.document.roles,
        "execution_profiles": snapshot.document.execution_profiles,
        "agents": snapshot.document.agents,
        "triggers": snapshot.document.triggers,
    }
    fields[collection] = values
    try:
        repository.replace(
            project_root,
            AgentsConfigDocument(snapshot.document.contract_version, **fields),
            expected_digest=snapshot.digest,
        )
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-AGC-002",
            kind="agents",
            message="failed to write global agents config",
            details={"path": "agents.yaml", "collection": collection},
        ) from exc


def _crud(
    project_root: Path,
    *,
    collection: str,
    identifier: str,
    parser: Callable[[dict[str, Any]], Any],
    encoder: Callable[[Any], dict[str, Any]],
    store_factory: Callable[[list[Any]], Any],
    item_id: str | None = None,
    item: dict[str, Any] | None = None,
    updates: dict[str, Any] | None = None,
    operation: str,
) -> Any:
    snapshot = _read(project_root)
    raw_values = [dict(value) for value in getattr(snapshot.document, collection)]
    values = store_factory([parser(value) for value in raw_values])
    if operation == "list":
        return [encoder(value) for value in values.list_all()]
    if operation == "get":
        return encoder(values.get(str(item_id)))
    if operation == "create":
        created = parser(item or {})
        values.add(created)
        result = encoder(created)
    elif operation == "update":
        existing = values.get(str(item_id))
        merged = encoder(existing)
        for key, value in (updates or {}).items():
            if key != identifier:
                merged[key] = value
        merged[identifier] = str(item_id)
        updated = parser(merged)
        if collection == "roles":
            values._roles[str(item_id)] = updated
        elif collection == "execution_profiles":
            values._profiles[str(item_id)] = updated
        elif collection == "agents":
            values._definitions[str(item_id)] = updated
        result = encoder(updated)
    elif operation == "delete":
        result = encoder(values.remove(str(item_id)))
    else:
        raise ValueError(operation)
    _replace_collection(
        project_root,
        collection=collection,
        values=tuple(encoder(value) for value in values.list_all()),
    )
    return result


def list_roles(project_root: Path) -> list[dict[str, Any]]:
    return _crud(project_root, collection="roles", identifier="role_id", parser=role_from_dict, encoder=role_to_dict, store_factory=RoleStore, operation="list")


def get_role(project_root: Path, role_id: str) -> dict[str, Any]:
    return _crud(project_root, collection="roles", identifier="role_id", parser=role_from_dict, encoder=role_to_dict, store_factory=RoleStore, item_id=role_id, operation="get")


def create_role(project_root: Path, role: dict[str, Any]) -> dict[str, Any]:
    return _crud(project_root, collection="roles", identifier="role_id", parser=role_from_dict, encoder=role_to_dict, store_factory=RoleStore, item=role, operation="create")


def update_role(project_root: Path, role_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return _crud(project_root, collection="roles", identifier="role_id", parser=role_from_dict, encoder=role_to_dict, store_factory=RoleStore, item_id=role_id, updates=updates, operation="update")


def delete_role(project_root: Path, role_id: str) -> dict[str, Any]:
    return _crud(project_root, collection="roles", identifier="role_id", parser=role_from_dict, encoder=role_to_dict, store_factory=RoleStore, item_id=role_id, operation="delete")


def list_execution_profiles(project_root: Path) -> list[dict[str, Any]]:
    return _crud(project_root, collection="execution_profiles", identifier="profile_id", parser=execution_profile_from_dict, encoder=execution_profile_to_dict, store_factory=ExecutionProfileStore, operation="list")


def get_execution_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    return _crud(project_root, collection="execution_profiles", identifier="profile_id", parser=execution_profile_from_dict, encoder=execution_profile_to_dict, store_factory=ExecutionProfileStore, item_id=profile_id, operation="get")


def create_execution_profile(project_root: Path, profile: dict[str, Any]) -> dict[str, Any]:
    return _crud(project_root, collection="execution_profiles", identifier="profile_id", parser=execution_profile_from_dict, encoder=execution_profile_to_dict, store_factory=ExecutionProfileStore, item=profile, operation="create")


def update_execution_profile(project_root: Path, profile_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return _crud(project_root, collection="execution_profiles", identifier="profile_id", parser=execution_profile_from_dict, encoder=execution_profile_to_dict, store_factory=ExecutionProfileStore, item_id=profile_id, updates=updates, operation="update")


def delete_execution_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    return _crud(project_root, collection="execution_profiles", identifier="profile_id", parser=execution_profile_from_dict, encoder=execution_profile_to_dict, store_factory=ExecutionProfileStore, item_id=profile_id, operation="delete")


def list_agent_definitions(project_root: Path) -> list[dict[str, Any]]:
    return _crud(project_root, collection="agents", identifier="agent_id", parser=agent_definition_from_dict, encoder=agent_definition_to_dict, store_factory=AgentDefinitionStore, operation="list")


def get_agent_definition(project_root: Path, agent_id: str) -> dict[str, Any]:
    return _crud(project_root, collection="agents", identifier="agent_id", parser=agent_definition_from_dict, encoder=agent_definition_to_dict, store_factory=AgentDefinitionStore, item_id=agent_id, operation="get")


def create_agent_definition(project_root: Path, definition: dict[str, Any]) -> dict[str, Any]:
    return _crud(project_root, collection="agents", identifier="agent_id", parser=agent_definition_from_dict, encoder=agent_definition_to_dict, store_factory=AgentDefinitionStore, item=definition, operation="create")


def update_agent_definition(project_root: Path, agent_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return _crud(project_root, collection="agents", identifier="agent_id", parser=agent_definition_from_dict, encoder=agent_definition_to_dict, store_factory=AgentDefinitionStore, item_id=agent_id, updates=updates, operation="update")


def delete_agent_definition(project_root: Path, agent_id: str) -> dict[str, Any]:
    return _crud(project_root, collection="agents", identifier="agent_id", parser=agent_definition_from_dict, encoder=agent_definition_to_dict, store_factory=AgentDefinitionStore, item_id=agent_id, operation="delete")
