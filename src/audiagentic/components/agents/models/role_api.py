"""Role API — load, save, CRUD (AS61).

Pure-logic module with no MCP coupling, mirroring agents_api.py's shape for
execution profiles. Role storage is machine-global and read fresh on every
call; ``project_root`` is retained only for API compatibility.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.components.agents.models.role import (
    RoleStore,
    role_from_dict,
    role_to_dict,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _repository() -> AgentsConfigRepository:
    """Use the machine-global catalog; project roots are not config authority."""
    return AgentsConfigRepository(global_agents_config_path(), required=True)


def load_roles(project_root: Path) -> RoleStore:
    """Load roles from the machine-global config file.

    Returns an empty store if the file doesn't exist.
    Raises AudiaGenticError(IO-ROL-001) on read failure.
    Raises AudiaGenticError(VAL-ROL-002) on contract-version mismatch.
    """
    snapshot = _repository().read(project_root)
    return RoleStore.from_dicts(list(snapshot.document.roles))


def save_roles(project_root: Path, store: RoleStore) -> None:
    """Serialize roles store back to the global YAML config file.

    Raises AudiaGenticError(IO-ROL-002) on write failure.
    """
    repository = _repository()
    snapshot = repository.read(project_root)
    document = AgentsConfigDocument(
        snapshot.document.contract_version,
        snapshot.document.prompts,
        tuple(store.to_dicts()),
        snapshot.document.execution_profiles,
        snapshot.document.agents,
        snapshot.document.triggers,
        snapshot.document.prompt_profiles,
    )
    try:
        repository.replace(project_root, document, expected_digest=snapshot.digest)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-ROL-002",
            kind="agents",
            message="failed to write roles config",
            details={"path": "agents.yaml", "error": str(exc)},
        ) from exc


def list_roles(project_root: Path) -> list[dict[str, Any]]:
    """List all roles as dicts."""
    store = load_roles(project_root)
    return [role_to_dict(r) for r in store.list_all()]


def get_role(project_root: Path, role_id: str) -> dict[str, Any]:
    """Get a specific role by ID.

    Raises AudiaGenticError(RES-ROL-001) if not found.
    """
    store = load_roles(project_root)
    role = store.get(role_id)
    return role_to_dict(role)


def create_role(project_root: Path, role_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new role.

    Validates uniqueness and writes to file.
    Raises AudiaGenticError(VAL-ROL-001) on validation failure.
    Raises AudiaGenticError(RES-ROL-002) on duplicate ID.
    Raises AudiaGenticError(IO-ROL-002) on write failure.
    """
    store = load_roles(project_root)
    role = role_from_dict(role_data)
    store.add(role)
    save_roles(project_root, store)
    return role_to_dict(role)


def update_role(project_root: Path, role_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update an existing role with merge semantics.

    role_id in updates is ignored (immutable).
    Raises AudiaGenticError(RES-ROL-001) if not found.
    Raises AudiaGenticError(VAL-ROL-001) on validation failure.
    Raises AudiaGenticError(IO-ROL-002) on write failure.
    """
    store = load_roles(project_root)
    existing = store.get(role_id)
    existing_dict = role_to_dict(existing)
    allowed_keys = {
        "instructions",
        "required_capabilities",
        "output_guidance",
        "runtime_tool_policy_ref",
        "description",
    }
    merged = dict(existing_dict)
    for key, value in updates.items():
        if key in allowed_keys:
            merged[key] = value
    merged["role_id"] = role_id
    new_role = role_from_dict(merged)
    store._roles[role_id] = new_role
    save_roles(project_root, store)
    return role_to_dict(new_role)


def delete_role(project_root: Path, role_id: str) -> dict[str, Any]:
    """Delete a role and return the deleted role data.

    Raises AudiaGenticError(RES-ROL-001) if not found.
    Raises AudiaGenticError(IO-ROL-002) on write failure.
    """
    store = load_roles(project_root)
    deleted = store.remove(role_id)
    save_roles(project_root, store)
    return role_to_dict(deleted)
