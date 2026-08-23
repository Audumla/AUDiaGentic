"""Execution profile API — load, save, CRUD, and resolution.

Pure-logic module with no MCP coupling. The machine-global catalog is the sole
authority; ``project_root`` is retained only for call-site compatibility.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import (
    AgentsConfigRepository,
    AgentsConfigValidationError,
)
from audiagentic.components.agents.models.execution_profile import (
    ExecutionProfileStore,
    execution_profile_from_dict,
    execution_profile_to_dict,
)
from audiagentic.foundation.components.hooks import ComponentStatusPayload
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _repository() -> AgentsConfigRepository:
    """Return the machine-global execution-profile authority."""
    return AgentsConfigRepository(global_agents_config_path(), required=True)


def load_execution_profiles(project_root: Path) -> ExecutionProfileStore:
    """Load execution profiles from the machine-global config file.

    Returns an empty store if the file doesn't exist.
    Raises AudiaGenticError(IO-EXP-001) on read failure.
    Raises AudiaGenticError(VAL-EXP-004) on contract-version mismatch.
    """
    try:
        snapshot = _repository().read(project_root)
    except AgentsConfigValidationError as exc:
        code = "VAL-EXP-004" if "contract-version" in str(exc) else "IO-EXP-001"
        raise AudiaGenticError(code=code, kind="agents", message=str(exc), details={}) from exc
    except Exception as exc:
        raise AudiaGenticError(code="IO-EXP-001", kind="agents", message="failed to read agents config", details={}) from exc
    return ExecutionProfileStore.from_dicts(list(snapshot.document.execution_profiles))


def save_execution_profiles(project_root: Path, store: ExecutionProfileStore) -> None:
    """Serialize profiles store back to the global YAML config file.

    Raises AudiaGenticError(IO-EXP-002) on write failure.
    """
    repository = _repository()
    snapshot = repository.read(project_root)
    document = AgentsConfigDocument(
        snapshot.document.contract_version,
        snapshot.document.prompts,
        snapshot.document.roles,
        tuple(store.to_dicts()),
        snapshot.document.agents,
        snapshot.document.triggers,
        snapshot.document.prompt_profiles,
    )
    try:
        repository.replace(project_root, document, expected_digest=snapshot.digest)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-EXP-002",
            kind="agents",
            message="failed to write execution profiles config",
            details={"path": "agents.yaml", "error": str(exc)},
        ) from exc


def seed_execution_profiles(project_root: Path) -> None:
    """Ensure the canonical Agents document has a default profile."""
    repository = _repository()
    snapshot = repository.read(project_root)
    if any(profile.get("is_default") for profile in snapshot.document.execution_profiles):
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
    document = AgentsConfigDocument(
        snapshot.document.contract_version,
        snapshot.document.prompts,
        snapshot.document.roles,
        (*snapshot.document.execution_profiles, execution_profile_to_dict(profile)),
        snapshot.document.agents,
        snapshot.document.triggers,
        snapshot.document.prompt_profiles,
    )
    repository.replace(
        project_root,
        document,
        expected_digest=snapshot.digest,
    )


def list_execution_profiles(project_root: Path) -> list[dict[str, Any]]:
    """List all execution profiles as dicts."""
    store = load_execution_profiles(project_root)
    return [execution_profile_to_dict(p) for p in store.list_all()]


def get_execution_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    """Get a specific profile by ID.

    Raises AudiaGenticError(RES-EXP-001) if not found.
    """
    store = load_execution_profiles(project_root)
    profile = store.get(profile_id)
    return execution_profile_to_dict(profile)


def create_execution_profile(project_root: Path, profile_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new execution profile.

    Validates uniqueness and writes to file.
    Raises AudiaGenticError(VAL-EXP-001) on validation failure.
    Raises AudiaGenticError(RES-EXP-002) on duplicate ID.
    Raises AudiaGenticError(IO-EXP-002) on write failure.
    """
    store = load_execution_profiles(project_root)
    profile = execution_profile_from_dict(profile_data)
    store.add(profile)
    save_execution_profiles(project_root, store)
    return execution_profile_to_dict(profile)


def update_execution_profile(
    project_root: Path, profile_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Update an existing profile with merge semantics.

    profile_id in updates is ignored (immutable).
    Raises AudiaGenticError(RES-EXP-001) if not found.
    Raises AudiaGenticError(VAL-EXP-001) on validation failure.
    Raises AudiaGenticError(IO-EXP-002) on write failure.
    """
    store = load_execution_profiles(project_root)
    existing = store.get(profile_id)
    existing_dict = execution_profile_to_dict(existing)
    allowed_keys = {"instances", "model_alias", "params", "is_default", "description", "provider_id"}
    merged = dict(existing_dict)
    for key, value in updates.items():
        if key in allowed_keys:
            merged[key] = value
    merged["profile_id"] = profile_id
    if merged.get("is_default"):
        for p in store.list_all():
            p.is_default = False
    new_profile = execution_profile_from_dict(merged)
    store._profiles[profile_id] = new_profile
    save_execution_profiles(project_root, store)
    return execution_profile_to_dict(new_profile)


def delete_execution_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    """Delete a profile and return the deleted profile data.

    Raises AudiaGenticError(RES-EXP-001) if not found.
    Raises AudiaGenticError(IO-EXP-002) on write failure.
    """
    store = load_execution_profiles(project_root)
    deleted = store.remove(profile_id)
    save_execution_profiles(project_root, store)
    return execution_profile_to_dict(deleted)


def resolve_execution_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    """Resolve a profile by ID for job execution.

    Returns a dict with provider_id, model_id, model_alias, and params.
    Raises AudiaGenticError(RES-EXP-001) if not found.
    """
    store = load_execution_profiles(project_root)
    profile = store.get(profile_id)
    return {
        "profile_id": profile.profile_id,
        "provider_id": profile.provider_id,
        "instances": list(profile.instances),
        "model_alias": profile.model_alias,
        "params": dict(profile.params),
        "surface_id": profile.surface_id,
    }


def resolve_default_execution_profile(project_root: Path) -> dict[str, Any]:
    """Resolve the default execution profile.

    Raises AudiaGenticError(RES-EXP-003) if no default exists.
    """
    store = load_execution_profiles(project_root)
    default = store.get_default()
    if default is None:
        raise AudiaGenticError(
            code="RES-EXP-003",
            kind="agents",
            message="no default execution profile configured",
            details={},
        )
    return {
        "profile_id": default.profile_id,
        "provider_id": default.provider_id,
        "instances": list(default.instances),
        "model_alias": default.model_alias,
        "params": dict(default.params),
        "surface_id": default.surface_id,
    }


def agent_status(project_root: Path) -> ComponentStatusPayload:
    """Component status-hook: profile count/default plus gateway overview.

    agents has no swappable-implementation concept (no options-schema per
    CREATING_A_COMPONENT.md §6/§11), so ``active_implementation`` is always
    None. ``configured`` reflects whether a default profile exists — without
    one, submitting a gateway request without an explicit execution-profile-id
    raises RES-EXP-003, so "profiles technically exist but the default
    gateway path is unusable" must not report as configured=True (RV37
    finding: overstated readiness).
    """
    from audiagentic.components.agents.gateway import api as agents_gateway_api
    from audiagentic.foundation.components import is_enabled

    store = load_execution_profiles(project_root)
    profiles = store.to_dicts()
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
