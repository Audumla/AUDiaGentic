"""The hosted agent catalog: legacy ``agents.yaml`` plus compiled agent files (CFG09).

Read-only. Agent files from the machine scopes (packaged templates and the
user configuration directory) compile to ordinary catalog records and win
over legacy entries with the same id. The legacy file is optional once agent
files exist; with neither, reads fail as before. Writes (management CRUD)
keep using ``AgentsConfigRepository`` on the legacy file only, so compiled
agents are never persisted into it. Project-scope agent files are not part
of the machine-wide gateway catalog in phase 1.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.agents_paths import global_agents_config_path

from .agent_files import compile_catalog, resolve_agents
from .contracts import AgentsConfigDocument
from .repository import (
    AgentsConfigRepository,
    AgentsConfigSnapshot,
    AgentsConfigValidationError,
    _digest,
)

_SECTIONS = ("prompts", "roles", "execution_profiles", "agents", "triggers")


def effective_catalog_mapping(project_root: Path | None = None) -> tuple[dict, list[str]]:
    """The merged catalog mapping and the agent ids where agent files override legacy entries."""
    del project_root  # the hosted catalog is machine-global
    legacy_path = global_agents_config_path()
    compiled = compile_catalog(resolve_agents(machine_only=True))
    has_agent_files = bool(compiled["agents"])
    if legacy_path.exists():
        legacy = AgentsConfigRepository(legacy_path, required=True).read(legacy_path.parent).document.to_mapping()
    elif has_agent_files:
        legacy = AgentsConfigDocument.from_mapping({"contract-version": "v2"}).to_mapping()
    else:
        raise AgentsConfigValidationError(f"required agents config is missing: {legacy_path}")
    clashes = sorted(set(legacy.get("agents", {})) & set(compiled["agents"]))
    merged = {"contract-version": legacy["contract-version"]}
    for section in _SECTIONS:
        merged[section] = {**legacy.get(section, {}), **compiled.get(section, {})}
    return merged, clashes


class EffectiveAgentsRepository:
    """Read-only repository over the effective hosted catalog."""

    def read(self, project_root: Path) -> AgentsConfigSnapshot:
        mapping, _ = effective_catalog_mapping(project_root)
        document = AgentsConfigDocument.from_mapping(mapping)
        return AgentsConfigSnapshot(document, _digest(document))
