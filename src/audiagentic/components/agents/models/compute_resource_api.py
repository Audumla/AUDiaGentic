"""Compute resource API — load, save, CRUD (AS105/AS101).

User-global config (audiagentic_home()) — no project_root parameter,
deliberately: a project must not be able to redefine the capacity of
hardware it does not own (AS105's closed override hazard).
"""
from __future__ import annotations

import logging
from typing import Any

from audiagentic.components.agents.agents_paths import compute_resources_path
from audiagentic.components.agents.models.compute_resource import (
    ComputeResourceStore,
    compute_resource_from_dict,
    compute_resource_to_dict,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file, save_yaml_file

logger = logging.getLogger(__name__)

_CONTRACT_VERSION = "v1"


def _load_yaml_lenient(path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return load_yaml_file(path)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-CRES-001",
            kind="agents",
            message="failed to read compute resources config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def load_compute_resources() -> ComputeResourceStore:
    """Load compute resources from the user-global config file.

    Returns an empty store if the file doesn't exist.
    Raises AudiaGenticError(IO-CRES-001) on read failure.
    Raises AudiaGenticError(VAL-CRES-004) on contract-version mismatch.
    """
    path = compute_resources_path()
    data = _load_yaml_lenient(path)
    if not data:
        return ComputeResourceStore()
    cv = data.get("contract-version")
    if cv and cv != _CONTRACT_VERSION:
        raise AudiaGenticError(
            code="VAL-CRES-004",
            kind="agents",
            message="unsupported compute resources contract version",
            details={"contract-version": cv, "expected": _CONTRACT_VERSION},
        )
    entries = data.get("resources", [])
    if not isinstance(entries, list):
        return ComputeResourceStore()
    return ComputeResourceStore.from_dicts(entries)


def save_compute_resources(store: ComputeResourceStore) -> None:
    """Raises AudiaGenticError(IO-CRES-002) on write failure."""
    path = compute_resources_path()
    payload = {"contract-version": _CONTRACT_VERSION, "resources": store.to_dicts()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_yaml_file(path, payload, sort_keys=False, atomic=True)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-CRES-002",
            kind="agents",
            message="failed to write compute resources config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def list_compute_resources() -> list[dict[str, Any]]:
    store = load_compute_resources()
    return [compute_resource_to_dict(r) for r in store.list_all()]


def get_compute_resource(resource_id: str) -> dict[str, Any]:
    """Raises AudiaGenticError(RES-CRES-001) if not found."""
    store = load_compute_resources()
    return compute_resource_to_dict(store.get(resource_id))


def create_compute_resource(resource_data: dict[str, Any]) -> dict[str, Any]:
    """Raises AudiaGenticError(VAL-CRES-001) on validation failure.
    Raises AudiaGenticError(RES-CRES-002) on duplicate ID.
    Raises AudiaGenticError(IO-CRES-002) on write failure.
    """
    store = load_compute_resources()
    resource = compute_resource_from_dict(resource_data)
    store.add(resource)
    save_compute_resources(store)
    return compute_resource_to_dict(resource)


def update_compute_resource(resource_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update with merge semantics. resource_id in updates is ignored (immutable).

    Raises AudiaGenticError(RES-CRES-001) if not found.
    Raises AudiaGenticError(VAL-CRES-001) on validation failure.
    Raises AudiaGenticError(IO-CRES-002) on write failure.
    """
    store = load_compute_resources()
    existing = store.get(resource_id)
    merged = compute_resource_to_dict(existing)
    allowed_keys = {"kind", "description"}
    for key, value in updates.items():
        if key in allowed_keys:
            merged[key] = value
    merged["resource_id"] = resource_id
    new_resource = compute_resource_from_dict(merged)
    store._resources[resource_id] = new_resource
    save_compute_resources(store)
    return compute_resource_to_dict(new_resource)


def delete_compute_resource(resource_id: str) -> dict[str, Any]:
    """Raises AudiaGenticError(RES-CRES-001) if not found."""
    store = load_compute_resources()
    removed = store.remove(resource_id)
    save_compute_resources(store)
    return compute_resource_to_dict(removed)
