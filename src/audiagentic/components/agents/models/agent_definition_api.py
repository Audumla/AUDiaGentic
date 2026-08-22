"""Agent Definition API — load, save, CRUD, and resolution (AS62).

Pure-logic module with no MCP coupling, mirroring roles_api.py's shape.
The machine-global catalog is the sole configuration authority; ``project_root``
is retained only for API compatibility.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.components.agents.models.agent_definition import (
    AgentDefinitionStore,
    agent_definition_from_dict,
    agent_definition_to_dict,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _repository() -> AgentsConfigRepository:
    """Return the machine-global agent catalog repository.

    ``project_root`` remains in the public API for protocol compatibility, but
    it is deliberately not an authority selector.  Hosted agent definitions
    are machine-global and must not be shadowed by a project-local document.
    """
    return AgentsConfigRepository(global_agents_config_path(), required=True)


def load_agent_definitions(project_root: Path) -> AgentDefinitionStore:
    """Load agent definitions from the project config file.

    Returns an empty store if the file doesn't exist.
    Raises AudiaGenticError(IO-AGD-001) on read failure.
    Raises AudiaGenticError(VAL-AGD-002) on contract-version mismatch.
    """
    snapshot = _repository().read(project_root)
    return AgentDefinitionStore.from_dicts(list(snapshot.document.agents))


def save_agent_definitions(project_root: Path, store: AgentDefinitionStore) -> None:
    """Serialize agent definitions store back to YAML config file.

    Raises AudiaGenticError(IO-AGD-002) on write failure.
    """
    repository = _repository()
    snapshot = repository.read(project_root)
    document = AgentsConfigDocument(
        snapshot.document.contract_version,
        snapshot.document.prompts,
        snapshot.document.roles,
        snapshot.document.execution_profiles,
        tuple(store.to_dicts()),
        snapshot.document.triggers,
        snapshot.document.prompt_profiles,
    )
    try:
        repository.replace(project_root, document, expected_digest=snapshot.digest)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-AGD-002",
            kind="agents",
            message="failed to write agent definitions config",
            details={"path": "agents.yaml", "error": str(exc)},
        ) from exc


def list_agent_definitions(project_root: Path) -> list[dict[str, Any]]:
    """List all agent definitions as dicts."""
    store = load_agent_definitions(project_root)
    return [agent_definition_to_dict(d) for d in store.list_all()]


def get_agent_definition(project_root: Path, agent_id: str) -> dict[str, Any]:
    """Get a specific agent definition by ID.

    Raises AudiaGenticError(RES-AGD-001) if not found.
    """
    store = load_agent_definitions(project_root)
    definition = store.get(agent_id)
    return agent_definition_to_dict(definition)


def create_agent_definition(project_root: Path, definition_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new agent definition.

    Validates uniqueness and writes to file. Does not validate that the
    referenced execution_profile_id/role_id exist -- that is
    resolve_agent_definition's job, at resolution time, not creation time,
    so definitions can be authored before their references (AS61/AS60
    stores are independent config files with no foreign-key enforcement).
    Raises AudiaGenticError(VAL-AGD-001) on validation failure.
    Raises AudiaGenticError(RES-AGD-002) on duplicate ID.
    Raises AudiaGenticError(IO-AGD-002) on write failure.
    """
    store = load_agent_definitions(project_root)
    definition = agent_definition_from_dict(definition_data)
    store.add(definition)
    save_agent_definitions(project_root, store)
    return agent_definition_to_dict(definition)


def update_agent_definition(
    project_root: Path, agent_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Update an existing agent definition with merge semantics.

    agent_id in updates is ignored (immutable) -- an Agent Definition can be
    re-pointed to a different compatible Execution Profile while keeping its
    stable public ID (AS62's reassessment gate), with no versioning
    infrastructure: this is a plain in-place field update, not a new record.
    Raises AudiaGenticError(RES-AGD-001) if not found.
    Raises AudiaGenticError(VAL-AGD-001) on validation failure.
    Raises AudiaGenticError(IO-AGD-002) on write failure.
    """
    store = load_agent_definitions(project_root)
    existing = store.get(agent_id)
    existing_dict = agent_definition_to_dict(existing)
    allowed_keys = {
        "name",
        "execution_profile_id",
        "role_ids",
        "prompt_id",
        "description",
        "advertised_skills",
        "internal",
        "acp",
        "a2a",
    }
    merged = dict(existing_dict)
    for key, value in updates.items():
        if key in allowed_keys:
            merged[key] = value
    merged["agent_id"] = agent_id
    new_definition = agent_definition_from_dict(merged)
    store._definitions[agent_id] = new_definition
    save_agent_definitions(project_root, store)
    return agent_definition_to_dict(new_definition)


def delete_agent_definition(project_root: Path, agent_id: str) -> dict[str, Any]:
    """Delete an agent definition and return the deleted data.

    Raises AudiaGenticError(RES-AGD-001) if not found.
    Raises AudiaGenticError(IO-AGD-002) on write failure.
    """
    store = load_agent_definitions(project_root)
    deleted = store.remove(agent_id)
    save_agent_definitions(project_root, store)
    return agent_definition_to_dict(deleted)


def resolve_agent_definition(
    project_root: Path,
    agent_id: str,
    *,
    execution_profile_lookup: Callable[[Path, str], dict[str, Any]] | None = None,
    role_lookup: Callable[[Path, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve an Agent Definition plus its Execution Profile and Role for admission.

    Returns a short-lived dict, not a durable record: launches no process,
    creates no session/task, and copies no definition into session state
    (AS62 do-not-add). Callers substitute fakes for `execution_profile_lookup`/
    `role_lookup` via plain-Python parameter injection (RV890) -- there is no
    composition graph involved, since resolution is stateless per-call.

    AS29 surface resolution (AS62 step 3 / AS82) happens at the admission
    boundary (`gateway/profiles.py::resolve_for_admission`), not here -- this
    is a definition-level preview, and resolving the surface a second time
    here would violate the resolve-once rule that boundary exists to enforce.
    `execution_profile["surface_id"]` (if set) is the raw, unresolved request;
    callers that need the *resolved* identity read it from the admission
    value, not from this preview.

    Raises AudiaGenticError(RES-AGD-001) if the agent definition is not found.
    Raises AudiaGenticError(RES-EXP-001) if its execution profile is not found.
    Raises AudiaGenticError(RES-ROL-001) if its role is not found.
    """
    if execution_profile_lookup is None:
        from audiagentic.components.agents.models.execution_profile_api import (
            get_execution_profile,
        )

        execution_profile_lookup = get_execution_profile
    if role_lookup is None:
        from audiagentic.components.agents.models.role_api import get_role

        role_lookup = get_role

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
