"""One-time migration from the three pre-v2 Agents config files."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.components.agents.models.prompt_definition import PromptDefinition
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.names import project_marker_path


def _legacy_path(project_root: Path, filename: str) -> Path:
    """Resolve an explicit pre-v2 input file during one-time migration only."""
    return project_marker_path(project_root) / "config" / filename


def build_legacy_document(project_root: Path) -> AgentsConfigDocument:
    """Read legacy files and build, but do not write, the canonical document."""
    roles_path = _legacy_path(project_root, "roles.yaml")
    profiles_path = _legacy_path(project_root, "execution-profiles.yaml")
    definitions_path = _legacy_path(project_root, "agent-definitions.yaml")
    roles_data = load_yaml_file(roles_path) if roles_path.exists() else {}
    profiles_data = load_yaml_file(profiles_path) if profiles_path.exists() else {}
    agents_data = load_yaml_file(definitions_path) if definitions_path.exists() else {}
    roles = tuple(roles_data.get("roles", []))
    prompts = tuple(PromptDefinition.from_dict({
            "prompt_id": f"migrated-role-{role['role_id']}",
            "content": [{"kind": "text", "text": role["instructions"]}],
            "input_schema": None,
            "description": role.get("description", ""),
        })
        for role in roles
    )
    profiles = tuple(profiles_data.get("profiles", []))
    agents = []
    for entry in agents_data.get("agent-definitions", []):
        migrated = dict(entry)
        role_id = migrated.pop("role_id", None)
        if role_id is not None and "role_ids" not in migrated:
            migrated["role_ids"] = [role_id]
        if role_id is not None:
            migrated["prompt_id"] = f"migrated-role-{role_id}"
        agents.append(migrated)
    return AgentsConfigDocument(
        contract_version="v2",
        prompts=prompts,
        roles=roles,
        execution_profiles=profiles,
        agents=tuple(agents),
    )


def migrate_legacy_config(project_root: Path) -> str:
    """Atomically create canonical config when absent; return its digest.

    Existing canonical configuration is never merged with legacy data.  The
    caller must compare it separately before considering legacy files retired.
    """
    repository = AgentsConfigRepository(global_agents_config_path(), required=False)
    # Legacy files are read from the project only as explicit migration input;
    # the canonical output is always the machine-global catalog.
    path = global_agents_config_path()
    if path.exists():
        return repository.read(project_root).digest
    document = build_legacy_document(project_root)
    return repository.replace(project_root, document, expected_digest=None).digest
