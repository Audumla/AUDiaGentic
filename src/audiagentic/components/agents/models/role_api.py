"""Role API — load, save, CRUD (AS61).

Pure-logic module with no MCP coupling, mirroring agents_api.py's shape for
execution profiles. Deliberately not composed: role storage is stateless
project-local config, read fresh on every call (see roles.RoleStore).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import roles_path
from audiagentic.components.agents.models.role import (
    RoleStore,
    role_from_dict,
    role_to_dict,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file, save_yaml_file

logger = logging.getLogger(__name__)

SEED_ROLES_YAML = """\
# Roles — small, reusable behavioral definitions independent of provider/model.
# Managed by the 'agents' component. Do not edit by hand unless you understand the schema.
contract-version: v1
roles: []
"""


def _load_yaml_lenient(path: Path) -> dict[str, Any]:
    """Load YAML without raising on missing file; returns empty dict."""
    if not path.exists():
        return {}
    try:
        return load_yaml_file(path)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-ROL-001",
            kind="agents",
            message="failed to read roles config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def load_roles(project_root: Path) -> RoleStore:
    """Load roles from the project config file.

    Returns an empty store if the file doesn't exist.
    Raises AudiaGenticError(IO-ROL-001) on read failure.
    Raises AudiaGenticError(VAL-ROL-002) on contract-version mismatch.
    """
    path = roles_path(project_root)
    data = _load_yaml_lenient(path)
    if not data:
        return RoleStore()
    cv = data.get("contract-version")
    if cv and cv != "v1":
        raise AudiaGenticError(
            code="VAL-ROL-002",
            kind="agents",
            message="unsupported roles contract version",
            details={"contract-version": cv, "expected": "v1"},
        )
    entries = data.get("roles", [])
    if not isinstance(entries, list):
        return RoleStore()
    store = RoleStore()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            role = role_from_dict(entry)
            store._roles[role.role_id] = role
        except AudiaGenticError:
            logger.warning("Skipping invalid role entry: %s", entry.get("role_id", "<unknown>"))
    return store


def save_roles(project_root: Path, store: RoleStore) -> None:
    """Serialize roles store back to YAML config file.

    Raises AudiaGenticError(IO-ROL-002) on write failure.
    """
    path = roles_path(project_root)
    payload = {
        "contract-version": "v1",
        "roles": store.to_dicts(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_yaml_file(path, payload, sort_keys=False, atomic=True)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-ROL-002",
            kind="agents",
            message="failed to write roles config",
            details={"path": str(path), "error": str(exc)},
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
