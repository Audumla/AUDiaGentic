"""Agent profile API — load, save, CRUD, and resolution.

Pure-logic module with no MCP coupling. Used by both the MCP servers and
any programmatic consumers (e.g., agent-jobs launch).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import agent_profiles_path
from audiagentic.components.agents.models import (
    AgentProfilesStore,
    profile_from_dict,
    profile_to_dict,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_text, load_yaml_file, save_yaml_file

logger = logging.getLogger(__name__)

SEED_PROFILES_YAML = """\
# Agent profiles — bind a provider to a specific model.
# Managed by the 'agents' component. Do not edit by hand unless you understand the schema.
contract-version: v1
profiles:
  - profile_id: default
    provider_id: local-openai
    model_id: gpt-4o
    is_default: true
    description: Default agent profile
"""


def _load_yaml_lenient(path: Path) -> dict[str, Any]:
    """Load YAML without raising on missing file; returns empty dict."""
    if not path.exists():
        return {}
    try:
        return load_yaml_file(path)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-AGP-001",
            kind="agents",
            message="failed to read agent profiles config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def load_profiles(project_root: Path) -> AgentProfilesStore:
    """Load agent profiles from the project config file.

    Returns an empty store if the file doesn't exist.
    Raises AudiaGenticError(IO-AGP-001) on read failure.
    Raises AudiaGenticError(VAL-AGP-004) on contract-version mismatch.
    """
    path = agent_profiles_path(project_root)
    data = _load_yaml_lenient(path)
    if not data:
        return AgentProfilesStore()
    cv = data.get("contract-version")
    if cv and cv != "v1":
        raise AudiaGenticError(
            code="VAL-AGP-004",
            kind="agents",
            message="unsupported agent profiles contract version",
            details={"contract-version": cv, "expected": "v1"},
        )
    entries = data.get("profiles", [])
    if not isinstance(entries, list):
        return AgentProfilesStore()
    store = AgentProfilesStore()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            profile = profile_from_dict(entry)
            store._profiles[profile.profile_id] = profile
        except AudiaGenticError:
            logger.warning(
                "Skipping invalid profile entry: %s", entry.get("profile_id", "<unknown>")
            )
    return store


def save_profiles(project_root: Path, store: AgentProfilesStore) -> None:
    """Serialize profiles store back to YAML config file.

    Raises AudiaGenticError(IO-AGP-002) on write failure.
    """
    path = agent_profiles_path(project_root)
    payload = {
        "contract-version": "v1",
        "profiles": store.to_dicts(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_yaml_file(path, payload, sort_keys=False, atomic=True)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-AGP-002",
            kind="agents",
            message="failed to write agent profiles config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def seed_profiles(project_root: Path) -> None:
    """Create the seed profiles file if it doesn't exist or is empty/stale."""
    path = agent_profiles_path(project_root)
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        if content and "contract-version" in content:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_text(path, SEED_PROFILES_YAML)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-AGP-002",
            kind="agents",
            message="failed to create seed agent profiles config",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def list_profiles(project_root: Path) -> list[dict[str, Any]]:
    """List all agent profiles as dicts."""
    store = load_profiles(project_root)
    return [profile_to_dict(p) for p in store.list_all()]


def get_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    """Get a specific profile by ID.

    Raises AudiaGenticError(RES-AGP-001) if not found.
    """
    store = load_profiles(project_root)
    profile = store.get(profile_id)
    return profile_to_dict(profile)


def create_profile(project_root: Path, profile_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new agent profile.

    Validates uniqueness and writes to file.
    Raises AudiaGenticError(VAL-AGP-001) on validation failure.
    Raises AudiaGenticError(RES-AGP-002) on duplicate ID.
    Raises AudiaGenticError(IO-AGP-002) on write failure.
    """
    store = load_profiles(project_root)
    profile = profile_from_dict(profile_data)
    store.add(profile)
    save_profiles(project_root, store)
    return profile_to_dict(profile)


def update_profile(project_root: Path, profile_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update an existing profile with merge semantics.

    profile_id in updates is ignored (immutable).
    Raises AudiaGenticError(RES-AGP-001) if not found.
    Raises AudiaGenticError(VAL-AGP-001) on validation failure.
    Raises AudiaGenticError(IO-AGP-002) on write failure.
    """
    store = load_profiles(project_root)
    existing = store.get(profile_id)
    existing_dict = profile_to_dict(existing)
    allowed_keys = {"model_id", "model_alias", "params", "is_default", "description", "provider_id"}
    merged = dict(existing_dict)
    for key, value in updates.items():
        if key in allowed_keys:
            merged[key] = value
    merged["profile_id"] = profile_id
    if merged.get("is_default"):
        for p in store.list_all():
            p.is_default = False
    new_profile = profile_from_dict(merged)
    store._profiles[profile_id] = new_profile
    save_profiles(project_root, store)
    return profile_to_dict(new_profile)


def delete_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    """Delete a profile and return the deleted profile data.

    Raises AudiaGenticError(RES-AGP-001) if not found.
    Raises AudiaGenticError(IO-AGP-002) on write failure.
    """
    store = load_profiles(project_root)
    deleted = store.remove(profile_id)
    save_profiles(project_root, store)
    return profile_to_dict(deleted)


def resolve_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    """Resolve a profile by ID for job execution.

    Returns a dict with provider_id, model_id, model_alias, and params.
    Raises AudiaGenticError(RES-AGP-001) if not found.
    """
    store = load_profiles(project_root)
    profile = store.get(profile_id)
    return {
        "profile_id": profile.profile_id,
        "provider_id": profile.provider_id,
        "model_id": profile.model_id,
        "model_alias": profile.model_alias,
        "params": dict(profile.params),
    }


def resolve_default_profile(project_root: Path) -> dict[str, Any]:
    """Resolve the default agent profile.

    Raises AudiaGenticError(RES-AGP-003) if no default exists.
    """
    store = load_profiles(project_root)
    default = store.get_default()
    if default is None:
        raise AudiaGenticError(
            code="RES-AGP-003",
            kind="agents",
            message="no default agent profile configured",
            details={},
        )
    return {
        "profile_id": default.profile_id,
        "provider_id": default.provider_id,
        "model_id": default.model_id,
        "model_alias": default.model_alias,
        "params": dict(default.params),
    }


def agent_status(project_root: Path) -> ComponentStatusPayload:
    """Component status-hook: profile count/default plus gateway overview.

    agents has no swappable-implementation concept (no options-schema per
    CREATING_A_COMPONENT.md §6/§11), so ``active_implementation`` is always
    None. ``configured`` reflects whether a default profile exists — without
    one, submitting a gateway request without an explicit agent-profile-id
    raises RES-AGP-003, so "profiles technically exist but the default
    gateway path is unusable" must not report as configured=True (RV37
    finding: overstated readiness).
    """
    from audiagentic.components.agents import agents_gateway_api
    from audiagentic.foundation.components import is_enabled
    from audiagentic.foundation.components.hooks import ComponentStatusPayload

    store = load_profiles(project_root)
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
