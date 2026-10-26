"""Global declarative agent selection, independent of execution-local facts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from audiagentic.foundation.contracts.errors import AudiaGenticError

if TYPE_CHECKING:
    from audiagentic.components.agents.configuration.repository import AgentsConfigSnapshot
    from audiagentic.components.agents.configuration.resolution import ResolvedAgentComposition


@dataclass(frozen=True, slots=True)
class AgentSemantics:
    """Global declarative identity; not expanded content or execution-local facts."""

    catalog: AgentsConfigSnapshot
    composition: ResolvedAgentComposition
    config_root: Path

    @property
    def execution_profile_id(self) -> str:
        return self.composition.execution_profile.profile_id

    @property
    def prompt_profile_id(self) -> str:
        return self.composition.prompt.prompt_id

    @property
    def composition_fingerprint(self) -> str:
        return self.composition.identity.fingerprint

    @property
    def prompt_definition_fingerprint(self) -> str:
        return self.composition.identity.prompt_definition_fingerprint


def resolve_agent_semantics(agent_id: str) -> AgentSemantics:
    """Resolve from one machine catalog snapshot without inspecting an execution root.

    Include IDs and file paths retain their existing declarative fingerprints;
    this does not expand prompt dependencies or commit to their file contents.
    """
    from audiagentic.components.agents.agents_paths import global_agents_config_path
    from audiagentic.components.agents.configuration.global_catalog import read_global_agents_config
    from audiagentic.components.agents.configuration.resolution import resolve_agent_composition

    catalog = read_global_agents_config()
    config_root = global_agents_config_path().parent
    try:
        # The resolver's path parameter is API-shape context only: the supplied
        # snapshot is the sole catalog authority, never a project-local lookup.
        composition = resolve_agent_composition(config_root, agent_id, snapshot=catalog)
    except KeyError as exc:
        raise AudiaGenticError(
            code="RES-AGD-001",
            kind="agents",
            message=f"agent definition not found: {agent_id!r}",
            details={"agent-id": agent_id},
        ) from exc
    return AgentSemantics(catalog=catalog, composition=composition, config_root=config_root)



__all__ = ["AgentSemantics", "resolve_agent_semantics"]
