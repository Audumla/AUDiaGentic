"""Agent Definition data model and storage (AS62).

An Agent Definition is a small logical composition: a stable ID/name/
description, one Execution Profile reference, one Role reference, optional
advertised skills, and publication flags (`internal`/`acp`/`a2a`) that are
authorization/visibility metadata only -- they do not install MCP servers,
grant management MCP access, alter harness runtime tools, or imply a
selected session surface supports ACP/A2A (AS65/AS66 validate that
separately).

Deliberately not composed (RV890, 2026-08-04): storage/resolution is plain
Python, mirroring Role and project-local Execution Profile resolution --
structurally the same stateless, project-scoped shape. See
ARCHITECTURE_STANDARDS.md §1 "Composition candidates".
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


@dataclass(init=False)
class AgentDefinition:
    """A logical agent with one prompt, many roles, and one profile.

    ``role_id`` remains accepted by the constructor and parser as a
    migration input, but ``role_ids`` is the only serialized authority.
    """
    agent_id: str
    name: str
    prompt_id: str | None
    role_ids: tuple[str, ...]
    execution_profile_id: str
    description: str = ""
    advertised_skills: list[str] = field(default_factory=list)
    internal: bool = True
    acp: bool = False
    a2a: bool = False
    # Stable prompt-profile identity.  This is deliberately distinct from
    # execution_profile_id, which binds provider/model execution.
    profile_id: str = "default"

    def __init__(
        self,
        *,
        agent_id: str,
        name: str,
        execution_profile_id: str,
        role_ids: tuple[str, ...] | list[str] | None = None,
        prompt_id: str | None = None,
        role_id: str | None = None,
        description: str = "",
        advertised_skills: list[str] | None = None,
        internal: bool = True,
        acp: bool = False,
        a2a: bool = False,
        profile_id: str = "default",
    ) -> None:
        selected_roles = tuple(role_ids or ((role_id,) if role_id else ()))
        self.agent_id = agent_id
        self.name = name
        self.prompt_id = prompt_id
        self.role_ids = selected_roles
        self.execution_profile_id = execution_profile_id
        self.description = description
        self.advertised_skills = list(advertised_skills or [])
        self.internal = internal
        self.acp = acp
        self.a2a = a2a
        self.profile_id = profile_id

    @property
    def role_id(self) -> str:
        """Compatibility read for pre-v2 callers; serialization uses role_ids."""
        return self.role_ids[0] if self.role_ids else ""


def validate_agent_definition(definition: dict[str, Any]) -> list[str]:
    """Validate an agent definition dict against the schema.

    Returns a list of issue strings. Empty list means valid.
    """
    issues: list[str] = []
    aid = definition.get("agent_id")
    if not aid or not isinstance(aid, str):
        issues.append("agent_id is required and must be a non-empty string")
    name = definition.get("name")
    if not name or not isinstance(name, str):
        issues.append("name is required and must be a non-empty string")
    profile_id = definition.get("execution_profile_id")
    if not profile_id or not isinstance(profile_id, str):
        issues.append("execution_profile_id is required and must be a non-empty string")
    role_ids = definition.get("role_ids", definition.get("role-id"))
    if role_ids is None and definition.get("role_id") is not None:
        role_ids = [definition["role_id"]]
    if not isinstance(role_ids, (list, tuple)) or not role_ids or not all(
        isinstance(item, str) and item.strip() for item in role_ids
    ):
        issues.append("role_ids is required and must be a non-empty list of strings")
    if "advertised_skills" in definition and definition["advertised_skills"] is not None:
        skills = definition["advertised_skills"]
        if not isinstance(skills, (list, tuple)) or not all(isinstance(item, str) for item in skills):
            issues.append("advertised_skills must be a list of strings")
    for flag in ("internal", "acp", "a2a"):
        if flag in definition and not isinstance(definition[flag], bool):
            issues.append(f"{flag} must be a boolean")
    if "profile_id" in definition and (
        not isinstance(definition["profile_id"], str) or not definition["profile_id"].strip()
    ):
        issues.append("profile_id must be a non-empty string")
    if "description" in definition and definition["description"] is not None:
        if not isinstance(definition["description"], str):
            issues.append("description must be a string or null")
    return issues


def agent_definition_from_dict(data: dict[str, Any]) -> AgentDefinition:
    """Construct an AgentDefinition from a dict with validation.

    Accepts both underscore and hyphen keys (YAML convention).
    Raises AudiaGenticError(VAL-AGD-001) if validation fails.
    """
    normalized = dict(data)
    for hyphen_key, underscore_key in (
        ("execution-profile-id", "execution_profile_id"),
        ("role-id", "role_id"),
        ("role-ids", "role_ids"),
        ("advertised-skills", "advertised_skills"),
        ("profile-id", "profile_id"),
    ):
        if hyphen_key in normalized and underscore_key not in normalized:
            normalized[underscore_key] = normalized.pop(hyphen_key)
    issues = validate_agent_definition(normalized)
    if issues:
        raise AudiaGenticError(
            code="VAL-AGD-001",
            kind="agents",
            message="agent definition failed validation",
            details={"agent_id": normalized.get("agent_id"), "issues": issues},
        )
    role_values = normalized.get("role_ids")
    if role_values is None and normalized.get("role_id") is not None:
        role_values = [normalized["role_id"]]
    return AgentDefinition(
        agent_id=str(normalized["agent_id"]).strip(),
        name=str(normalized["name"]).strip(),
        execution_profile_id=str(normalized["execution_profile_id"]).strip(),
        prompt_id=(str(normalized["prompt_id"]).strip() if normalized.get("prompt_id") else None),
        role_ids=tuple(str(value).strip() for value in role_values),
        description=str(normalized.get("description") or "").strip(),
        advertised_skills=list(normalized.get("advertised_skills") or []),
        internal=bool(normalized.get("internal", True)),
        acp=bool(normalized.get("acp", False)),
        a2a=bool(normalized.get("a2a", False)),
        profile_id=str(normalized.get("profile_id") or "default").strip(),
    )


def agent_definition_to_dict(definition: AgentDefinition) -> dict[str, Any]:
    """Serialize an AgentDefinition to a dict for YAML round-trip."""
    data = asdict(definition)
    data["role_ids"] = list(definition.role_ids)
    return data


class AgentDefinitionStore:
    """In-memory store for agent definitions with CRUD operations.

    Deliberately not composed -- see module docstring.
    """

    def __init__(self, definitions: list[AgentDefinition] | None = None) -> None:
        self._definitions: dict[str, AgentDefinition] = {}
        if definitions:
            for d in definitions:
                self._definitions[d.agent_id] = d

    def get(self, agent_id: str) -> AgentDefinition:
        """Get a definition by ID.

        Raises AudiaGenticError(RES-AGD-001) if not found.
        """
        definition = self._definitions.get(agent_id)
        if definition is None:
            raise AudiaGenticError(
                code="RES-AGD-001",
                kind="agents",
                message="agent definition not found",
                details={"agent_id": agent_id},
            )
        return definition

    def list_all(self) -> list[AgentDefinition]:
        """Return all definitions as a list."""
        return list(self._definitions.values())

    def add(self, definition: AgentDefinition) -> None:
        """Add a definition. Raises AudiaGenticError(RES-AGD-002) if ID already exists."""
        if definition.agent_id in self._definitions:
            raise AudiaGenticError(
                code="RES-AGD-002",
                kind="agents",
                message="agent definition ID already exists",
                details={"agent_id": definition.agent_id},
            )
        self._definitions[definition.agent_id] = definition

    def remove(self, agent_id: str) -> AgentDefinition:
        """Remove and return a definition. Raises AudiaGenticError(RES-AGD-001) if not found."""
        definition = self.get(agent_id)
        del self._definitions[agent_id]
        return definition

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialize all definitions to dicts."""
        return [agent_definition_to_dict(d) for d in self._definitions.values()]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]], *, strict: bool = False) -> AgentDefinitionStore:
        """Construct a store from a list of definition dicts."""
        definitions = []
        for entry in data:
            try:
                definitions.append(agent_definition_from_dict(entry))
            except AudiaGenticError:
                if strict:
                    raise
                logger.warning(
                    "Skipping invalid agent definition entry: %s", entry.get("agent_id", "<unknown>")
                )
        return cls(definitions)
