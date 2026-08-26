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
from audiagentic.foundation.components.hooks import ComponentStatusPayload
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .contracts import AgentsConfigDocument
from .repository import AgentsConfigRepository


def _repository() -> AgentsConfigRepository:
    # Management reads tolerate a fresh installation with no catalog yet;
    # hosted admission uses the required repository path independently.
    return AgentsConfigRepository(global_agents_config_path(), required=False)


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
            expected_digest=snapshot.digest if global_agents_config_path().exists() else None,
        )
    except Exception as exc:
        error_code = {
            "roles": "IO-ROL-002",
            "execution_profiles": "IO-EXP-002",
            "agents": "IO-AGD-002",
        }.get(collection, "IO-AGC-002")
        raise AudiaGenticError(
            code=error_code,
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
            if getattr(updated, "is_default", False):
                from dataclasses import replace

                for existing_id, existing in list(values._profiles.items()):
                    if existing_id != str(item_id) and existing.is_default:
                        values._profiles[existing_id] = replace(existing, is_default=False)
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


# Typed-store projections used by execution and diagnostics.  These are kept
# in the canonical management module so callers never need a second authority
# module merely to read or resolve a catalog collection.
def load_execution_profiles(project_root: Path) -> ExecutionProfileStore:
    try:
        snapshot = _read(project_root)
    except Exception as exc:
        message = str(exc)
        code = "VAL-EXP-004" if "contract-version" in message else "IO-EXP-001"
        raise AudiaGenticError(code=code, kind="agents", message="failed to read execution profiles", details={}) from exc
    return ExecutionProfileStore.from_dicts(list(snapshot.document.execution_profiles))


def save_execution_profiles(project_root: Path, store: ExecutionProfileStore) -> None:
    _replace_collection(
        project_root,
        collection="execution_profiles",
        values=tuple(store.to_dicts()),
    )


def seed_execution_profiles(project_root: Path) -> None:
    try:
        store = load_execution_profiles(project_root)
    except AudiaGenticError:
        path = global_agents_config_path()
        if path.exists():
            path.unlink()
        store = ExecutionProfileStore()
    if store.get_default() is not None:
        return
    profile = execution_profile_from_dict(
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "instances": ["default"],
            "is_default": True,
            "description": "Default execution profile",
        }
    )
    store.add(profile)
    save_execution_profiles(project_root, store)


def resolve_execution_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    profile = load_execution_profiles(project_root).get(profile_id)
    return {
        "profile_id": profile.profile_id,
        "provider_id": profile.provider_id,
        "instances": list(profile.instances),
        "model_alias": profile.model_alias,
        "params": dict(profile.params),
        "surface_id": profile.surface_id,
    }


def resolve_default_execution_profile(project_root: Path) -> dict[str, Any]:
    profile = load_execution_profiles(project_root).get_default()
    if profile is None:
        raise AudiaGenticError(
            code="RES-EXP-003",
            kind="agents",
            message="no default execution profile configured",
            details={},
        )
    return {
        "profile_id": profile.profile_id,
        "provider_id": profile.provider_id,
        "instances": list(profile.instances),
        "model_alias": profile.model_alias,
        "params": dict(profile.params),
        "surface_id": profile.surface_id,
    }


def load_roles(project_root: Path) -> RoleStore:
    snapshot = _read(project_root)
    return RoleStore.from_dicts(list(snapshot.document.roles))


def save_roles(project_root: Path, store: RoleStore) -> None:
    _replace_collection(project_root, collection="roles", values=tuple(store.to_dicts()))


def load_agent_definitions(project_root: Path) -> AgentDefinitionStore:
    snapshot = _read(project_root)
    return AgentDefinitionStore.from_dicts(list(snapshot.document.agents))


def save_agent_definitions(project_root: Path, store: AgentDefinitionStore) -> None:
    _replace_collection(project_root, collection="agents", values=tuple(store.to_dicts()))


def resolve_agent_definition(
    project_root: Path,
    agent_id: str,
    *,
    execution_profile_lookup: Callable[[Path, str], dict[str, Any]] | None = None,
    role_lookup: Callable[[Path, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    execution_profile_lookup = execution_profile_lookup or get_execution_profile
    role_lookup = role_lookup or get_role
    definition = get_agent_definition(project_root, agent_id)
    profile = execution_profile_lookup(project_root, definition["execution_profile_id"])
    role_ids = definition.get("role_ids") or [definition.get("role_id")]
    roles = [role_lookup(project_root, role_id) for role_id in role_ids if role_id]
    return {
        "agent_id": definition["agent_id"],
        "name": definition["name"],
        "execution_profile": profile,
        "roles": roles,
        "advertised_skills": definition["advertised_skills"],
        "publication": {
            "internal": definition["internal"],
            "acp": definition["acp"],
            "a2a": definition["a2a"],
        },
    }


def agent_status(project_root: Path) -> ComponentStatusPayload:
    from audiagentic.components.agents.gateway import api as agents_gateway_api
    from audiagentic.foundation.components import is_enabled

    profiles = list_execution_profiles(project_root)
    default_id = next((p["profile_id"] for p in profiles if p.get("is_default")), None)
    return ComponentStatusPayload(
        enabled=is_enabled("agents", project_root),
        configured=default_id is not None,
        active_implementation=None,
        missing_required=[],
        details={
            "profile_count": len(profiles),
            "default_profile_id": default_id,
            "gateway": agents_gateway_api.gateway_overview(project_root),
        },
    )
