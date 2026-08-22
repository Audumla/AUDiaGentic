from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.configuration.global_catalog import global_agents_repository
from audiagentic.components.agents.configuration.resolution import resolve_agent_composition
from audiagentic.components.agents.context.contracts import AgentContextRecord, AgentContextState
from audiagentic.components.agents.context.store import AgentContextStore


def open_context(project_root: Path, agent_id: str, title: str | None = None) -> AgentContextRecord:
    # A hosted gateway installs the shared profile registry and therefore
    # resolves composition from the machine-global catalog. Embedded callers
    # (including isolated project tests) retain the context library's local
    # resolver; this seam is never used by the shared gateway process.
    from audiagentic.components.agents.gateway.profiles import get_gateway_registry

    repository = global_agents_repository() if get_gateway_registry() is not None else None
    composition = resolve_agent_composition(project_root, agent_id, repository=repository)
    return AgentContextStore().create(project_root, composition.identity, title)


def get_context(project_root: Path, context_id: str) -> AgentContextRecord:
    return AgentContextStore().get(project_root, context_id)


def list_contexts(project_root: Path) -> tuple[AgentContextRecord, ...]:
    return AgentContextStore().list(project_root)


def close_context(project_root: Path, context_id: str) -> AgentContextRecord:
    current = get_context(project_root, context_id)
    return AgentContextStore().transition(project_root, context_id, AgentContextState.CLOSED, expected_revision=current.revision)
