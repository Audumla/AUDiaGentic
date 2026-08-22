"""Machine-global Agent catalog reads used by shared gateway surfaces."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.repository import (
    AgentsConfigRepository,
    AgentsConfigSnapshot,
)
from audiagentic.components.agents.models.agent_definition import (
    AgentDefinitionStore,
    agent_definition_to_dict,
)
from audiagentic.components.agents.models.execution_profile import (
    execution_profile_from_dict,
    execution_profile_to_dict,
)
from audiagentic.components.agents.models.role import role_from_dict
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.components.providers.services.execution.agent_prompt_profiles import known_profile_ids


def global_agents_repository() -> AgentsConfigRepository:
    return AgentsConfigRepository(global_agents_config_path(), required=True)


def read_global_agents_config(project_root: Path | None = None) -> AgentsConfigSnapshot:
    """Read the machine catalog; project_root is only API-shape context."""
    snapshot = global_agents_repository().read(project_root or Path.cwd())
    # A machine execution authority is all-or-nothing. Validate every typed
    # collection before publishing any discovery result; tolerant CRUD stores
    # must not turn one malformed record into a partially valid catalog.
    for role in snapshot.document.roles:
        role_from_dict(dict(role))
    for profile in snapshot.document.execution_profiles:
        execution_profile_from_dict(dict(profile))
    AgentDefinitionStore.from_dicts(list(snapshot.document.agents), strict=True)
    for agent in snapshot.document.agents:
        profile_id = agent.get("profile_id", "default")
        if profile_id not in known_profile_ids():
            raise AudiaGenticError(
                code="VAL-AGD-002",
                kind="agents",
                message="unknown global agent prompt profile",
                details={"profile-id": profile_id, "known": list(known_profile_ids())},
            )
    return snapshot


def list_global_agent_definitions(project_root: Path | None = None) -> list[dict[str, Any]]:
    snapshot = read_global_agents_config(project_root)
    store = AgentDefinitionStore.from_dicts(list(snapshot.document.agents), strict=True)
    return [agent_definition_to_dict(item) for item in store.list_all()]


def get_global_agent_definition(project_root: Path, agent_id: str) -> dict[str, Any]:
    store = AgentDefinitionStore.from_dicts(list(read_global_agents_config(project_root).document.agents), strict=True)
    return agent_definition_to_dict(store.get(agent_id))


def resolve_global_execution_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    snapshot = read_global_agents_config(project_root)
    raw = next(
        (item for item in snapshot.document.execution_profiles if item.get("profile_id") == profile_id),
        None,
    )
    if raw is None:
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        raise AudiaGenticError(
            code="RES-EXP-001",
            kind="agents",
            message=f"global execution profile not found: {profile_id!r}",
            details={"profile-id": profile_id},
        )
    return execution_profile_to_dict(execution_profile_from_dict(raw))


def resolve_global_default_execution_profile(project_root: Path) -> dict[str, Any]:
    """Resolve the sole default execution profile from the machine catalog."""
    snapshot = read_global_agents_config(project_root)
    raw = next(
        (item for item in snapshot.document.execution_profiles if item.get("is_default") is True),
        None,
    )
    if raw is None:
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        raise AudiaGenticError(
            code="RES-EXP-002",
            kind="agents",
            message="global agents catalog has no default execution profile",
            details={"path": str(global_agents_config_path())},
        )
    return execution_profile_to_dict(execution_profile_from_dict(raw))


__all__ = [
    "get_global_agent_definition",
    "global_agents_repository",
    "list_global_agent_definitions",
    "read_global_agents_config",
    "resolve_global_execution_profile",
    "resolve_global_default_execution_profile",
]
