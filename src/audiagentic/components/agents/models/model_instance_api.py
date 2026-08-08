"""Model instance API — load, save, CRUD (AS105/AS101).

User-global config (audiagentic_home()) — no project_root parameter,
deliberately: a project must not be able to redefine the capacity of
hardware it does not own (AS105's closed override hazard).
"""
from __future__ import annotations

import logging
from typing import Any

from audiagentic.components.agents.agents_paths import model_instances_path
from audiagentic.components.agents.models.model_instance import (
    ModelInstanceStore,
    model_instance_from_dict,
    model_instance_to_dict,
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
            code="IO-MINST-001",
            kind="agents",
            message="failed to read model instances config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def load_model_instances() -> ModelInstanceStore:
    """Load model instances from the user-global config file.

    Returns an empty store if the file doesn't exist.
    Raises AudiaGenticError(IO-MINST-001) on read failure.
    Raises AudiaGenticError(VAL-MINST-004) on contract-version mismatch.
    """
    path = model_instances_path()
    data = _load_yaml_lenient(path)
    if not data:
        return ModelInstanceStore()
    cv = data.get("contract-version")
    if cv and cv != _CONTRACT_VERSION:
        raise AudiaGenticError(
            code="VAL-MINST-004",
            kind="agents",
            message="unsupported model instances contract version",
            details={"contract-version": cv, "expected": _CONTRACT_VERSION},
        )
    entries = data.get("instances", [])
    if not isinstance(entries, list):
        return ModelInstanceStore()
    return ModelInstanceStore.from_dicts(entries)


def save_model_instances(store: ModelInstanceStore) -> None:
    """Raises AudiaGenticError(IO-MINST-002) on write failure."""
    path = model_instances_path()
    payload = {"contract-version": _CONTRACT_VERSION, "instances": store.to_dicts()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_yaml_file(path, payload, sort_keys=False, atomic=True)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-MINST-002",
            kind="agents",
            message="failed to write model instances config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def list_model_instances() -> list[dict[str, Any]]:
    store = load_model_instances()
    return [model_instance_to_dict(i) for i in store.list_all()]


def get_model_instance(instance_id: str) -> dict[str, Any]:
    """Raises AudiaGenticError(RES-MINST-001) if not found."""
    store = load_model_instances()
    return model_instance_to_dict(store.get(instance_id))


def list_instances_serving(model: str) -> list[dict[str, Any]]:
    """All instances that can serve `model` -- the compatible-instance set
    a profile naming this model resolves to."""
    store = load_model_instances()
    return [model_instance_to_dict(i) for i in store.list_serving(model)]


def create_model_instance(instance_data: dict[str, Any]) -> dict[str, Any]:
    """Raises AudiaGenticError(VAL-MINST-001) on validation failure.
    Raises AudiaGenticError(RES-MINST-002) on duplicate ID.
    Raises AudiaGenticError(IO-MINST-002) on write failure.
    """
    store = load_model_instances()
    instance = model_instance_from_dict(instance_data)
    store.add(instance)
    save_model_instances(store)
    return model_instance_to_dict(instance)


def update_model_instance(instance_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update with merge semantics. instance_id in updates is ignored (immutable).

    Raises AudiaGenticError(RES-MINST-001) if not found.
    Raises AudiaGenticError(VAL-MINST-001) on validation failure.
    Raises AudiaGenticError(IO-MINST-002) on write failure.
    """
    store = load_model_instances()
    existing = store.get(instance_id)
    merged = model_instance_to_dict(existing)
    allowed_keys = {"resource_id", "servable_models", "logical_model", "loaded_model", "description"}
    for key, value in updates.items():
        if key in allowed_keys:
            merged[key] = value
    merged["instance_id"] = instance_id
    new_instance = model_instance_from_dict(merged)
    store._instances[instance_id] = new_instance
    save_model_instances(store)
    return model_instance_to_dict(new_instance)


def delete_model_instance(instance_id: str) -> dict[str, Any]:
    """Raises AudiaGenticError(RES-MINST-001) if not found."""
    store = load_model_instances()
    removed = store.remove(instance_id)
    save_model_instances(store)
    return model_instance_to_dict(removed)
