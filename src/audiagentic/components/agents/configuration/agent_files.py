"""Agent definitions as single validated files with templates (CFG05).

Contract: docs/design/configuration-model.md. One agent per file in a scope's
``agents/`` directory and one template per file in ``templates/``. Scopes,
lowest first: vendor templates shipped in ``config/components/agents/templates``,
user (platform config dir) and project (current checkout's ``.audiagentic``).
A higher scope's file with the same id merge-patches (RFC 7396) over the lower
one; an agent may ``extends`` one template (one level). Each resolved agent
compiles to the existing prompt, role, execution-profile and agent records,
so current catalog consumers see ordinary entries.

Mechanics come from foundation (strict YAML, merge, discovery, schema
registry); this module owns only agent semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.config.merge import Origin, merge_patch, without_nulls
from audiagentic.foundation.config.settings import discover_project_root, project_config_dir
from audiagentic.foundation.config.strict_yaml import json_pointer, load_settings_file
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.foundation.paths.home import user_config_dir
from audiagentic.foundation.paths.names import get_component_config_dirs

agent_file_error = make_error_factory("CFG", "AGF", "agents")

DEFAULT_PROMPT = "{prompt-body}"
_AGENT_ONLY = {"extends"}


@dataclass(frozen=True)
class AgentFileSource:
    scope: str
    kind: str  # "agents" or "templates"
    path: Path


@dataclass(frozen=True)
class ResolvedAgent:
    agent_id: str
    fields: dict[str, Any]
    origins: dict[str, Origin]
    files: tuple[Path, ...]
    template: str | None

    def to_catalog_records(self) -> dict[str, dict[str, Any]]:
        """Compile to the existing Agents document records (one of each)."""
        from audiagentic.components.providers.providers_api import provider_target_key

        fields = self.fields
        profile: dict[str, Any] = {
            "provider_id": provider_target_key(fields["provider"], fields.get("instance")),
            "instances": [fields["model"]],
            "params": dict(fields.get("params", {})),
            "description": fields.get("description", ""),
        }
        if fields.get("surface"):
            profile["surface_id"] = fields["surface"]
        return {
            "prompts": {self.agent_id: {"description": fields.get("description", ""),
                                        "content": [{"kind": "text", "text": fields.get("prompt", DEFAULT_PROMPT)}]}},
            "roles": {self.agent_id: {"instructions": fields["instructions"],
                                      "description": fields.get("description", "")}},
            "execution_profiles": {self.agent_id: profile},
            "agents": {self.agent_id: {"name": fields.get("name", self.agent_id),
                                       "description": fields.get("description", ""),
                                       "prompt_id": self.agent_id, "role_ids": [self.agent_id],
                                       "execution_profile_id": self.agent_id,
                                       "advertised_skills": list(fields.get("skills", []))}},
        }


def agent_file_sources(project_root: Path | None) -> list[AgentFileSource]:
    sources: list[AgentFileSource] = []
    for base in get_component_config_dirs():
        sources += [AgentFileSource("vendor", "templates", path)
                    for path in sorted((base / "agents" / "templates").glob("*.yaml"))]
    scope_dirs = [("user", user_config_dir())]
    if project_root is not None:
        scope_dirs.append(("project", project_config_dir(project_root)))
    for scope, directory in scope_dirs:
        for kind in ("templates", "agents"):
            sources += [AgentFileSource(scope, kind, path) for path in sorted((directory / kind).glob("*.yaml"))]
    return sources


def _validator() -> Draft202012Validator:
    return Draft202012Validator(read_schema("agent-file"))


def _loaded(sources: list[AgentFileSource]) -> dict[tuple[str, str], list[tuple[AgentFileSource, Any]]]:
    """Validate every file and group them by (kind, id), lowest scope first."""
    validator = _validator()
    grouped: dict[tuple[str, str], list[tuple[AgentFileSource, Any]]] = {}
    for source in sources:
        document = load_settings_file(source.path)
        for error in sorted(validator.iter_errors(without_nulls(document.data)), key=lambda e: list(e.absolute_path)):
            parts = tuple(error.absolute_path)
            position = document.positions.get(json_pointer(parts)) or document.positions.get(json_pointer(parts[:1]))
            raise agent_file_error(1, f"Invalid {source.kind[:-1]} file: {error.message}", file=str(source.path),
                                   line=position.line if position else None, pointer=json_pointer(parts) or "/")
        declared = document.data.get("id")
        if declared is not None and declared != source.path.stem:
            raise agent_file_error(6, "File id does not match its file name", file=str(source.path), id=declared)
        if source.kind == "templates" and set(document.data) & _AGENT_ONLY:
            raise agent_file_error(2, "Templates cannot extend another template", file=str(source.path))
        grouped.setdefault((source.kind, source.path.stem), []).append((source, document))
    return grouped


def _apply(fields: dict[str, Any], origins: dict[str, Origin],
           layers: list[tuple[AgentFileSource, Any]]) -> dict[str, Any]:
    """Merge-patch each file over ``fields`` in order (RFC 7396: null deletes)."""
    for source, document in layers:
        patch = {key: value for key, value in document.data.items() if key not in ("id", "schema_version")}

        def origin_of(pointer: str, _source=source, _document=document) -> Origin:
            position = _document.positions.get(pointer)
            return Origin(_source.scope, str(_source.path), position.line if position else None,
                          position.column if position else None)

        fields = merge_patch(fields, patch, origins, origin_of)
    return fields


def _instructions(fields: dict[str, Any], origins: dict[str, Origin], agent_id: str) -> None:
    path_text = fields.pop("instructions_file", None)
    if path_text is None:
        return
    declaring = origins.get("/instructions_file")
    base = Path(declaring.file).parent if declaring and declaring.file else Path.cwd()
    path = (base / path_text).resolve()
    try:
        fields["instructions"] = path.read_text(encoding="utf-8")
    except OSError as error:
        raise agent_file_error(5, "Cannot read instructions_file", agent=agent_id, file=str(path),
                               reason=error.strerror) from None


def _default_surface(fields: dict[str, Any], agent_id: str) -> None:
    if fields.get("surface"):
        return
    from audiagentic.components.providers.providers_api import list_session_surface_ids

    surfaces = list_session_surface_ids(fields["provider"])
    if len(surfaces) == 1:
        fields["surface"] = surfaces[0]
    elif len(surfaces) > 1:
        raise agent_file_error(4, "Provider has several session surfaces; set surface", agent=agent_id,
                               provider=fields["provider"], surfaces=list(surfaces))


def resolve_agents(
    *, project: Path | str | None = None, cwd: Path | None = None, machine_only: bool = False,
) -> dict[str, ResolvedAgent]:
    """Resolve agents from vendor, user and (unless ``machine_only``) project scopes."""
    project_root = None if machine_only else discover_project_root(project, cwd=cwd)
    grouped = _loaded(agent_file_sources(project_root))
    resolved: dict[str, ResolvedAgent] = {}
    for (kind, agent_id), layers in sorted(grouped.items()):
        if kind != "agents":
            continue
        origins: dict[str, Origin] = {}
        template_id = _apply({}, {}, layers).get("extends")
        fields: dict[str, Any] = {}
        template_layers: list[tuple[AgentFileSource, Any]] = []
        if template_id is not None:
            template_layers = grouped.get(("templates", template_id), [])
            if not template_layers:
                raise agent_file_error(2, "Agent extends an unknown template", agent=agent_id, template=template_id)
            fields = _apply(fields, origins, template_layers)
        fields = _apply(fields, origins, layers)
        fields.pop("extends", None)
        origins.pop("/extends", None)
        files = [source.path for source, _ in (*template_layers, *layers)]
        _instructions(fields, origins, agent_id)
        missing = [name for name in ("provider", "model", "instructions") if not fields.get(name)]
        if missing:
            raise agent_file_error(3, "Resolved agent is incomplete", agent=agent_id, missing=missing,
                                   files=[str(path) for path in files])
        _default_surface(fields, agent_id)
        resolved[agent_id] = ResolvedAgent(agent_id, fields, origins, tuple(files), template_id)
    return resolved


def compile_catalog(agents: dict[str, ResolvedAgent]) -> dict[str, Any]:
    """An Agents document mapping (contract v2) holding every resolved agent."""
    document: dict[str, Any] = {"contract-version": "v2", "prompts": {}, "roles": {},
                                "execution_profiles": {}, "agents": {}, "triggers": {}}
    for agent in agents.values():
        for section, records in agent.to_catalog_records().items():
            document[section].update(records)
    return document
