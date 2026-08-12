"""Role data model and storage (AS61).

A Role is a small, provider-independent behavioral definition: instructions,
simple required capabilities where a demonstrated Role needs them, optional
output guidance, and an inert runtime-tool-policy reference with no runtime
effect. It carries no provider/model selection, session surface, queue, or
runtime tool/MCP/permission configuration -- those stay owned by
ExecutionProfile and the harness's existing configuration.

`instructions` is a plain string or opaque reference (RV889, 2026-08-04): not
a reuse-dependency on `agent_jobs/prompt_templates.py`'s `@tag` mechanism,
which is slated for rework. See project memory
`project_agent_jobs_rework_pending.md`.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


@dataclass
class Role:
    """A small reusable behavioral definition, independent of provider/model."""
    role_id: str
    instructions: str
    required_capabilities: list[str] = field(default_factory=list)
    output_guidance: str | None = None
    runtime_tool_policy_ref: str | None = None
    description: str = ""


def validate_role(role: dict[str, Any]) -> list[str]:
    """Validate a role dict against the role schema.

    Returns a list of issue strings. Empty list means valid.
    """
    issues: list[str] = []
    rid = role.get("role_id")
    if not rid or not isinstance(rid, str):
        issues.append("role_id is required and must be a non-empty string")
    instructions = role.get("instructions")
    if not instructions or not isinstance(instructions, str):
        issues.append("instructions is required and must be a non-empty string")
    if "required_capabilities" in role and role["required_capabilities"] is not None:
        capabilities = role["required_capabilities"]
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) for item in capabilities
        ):
            issues.append("required_capabilities must be a list of strings")
    if "output_guidance" in role and role["output_guidance"] is not None:
        if not isinstance(role["output_guidance"], str):
            issues.append("output_guidance must be a string or null")
    if "runtime_tool_policy_ref" in role and role["runtime_tool_policy_ref"] is not None:
        if not isinstance(role["runtime_tool_policy_ref"], str):
            issues.append("runtime_tool_policy_ref must be a string or null")
    if "description" in role and role["description"] is not None:
        if not isinstance(role["description"], str):
            issues.append("description must be a string or null")
    return issues


def role_from_dict(data: dict[str, Any]) -> Role:
    """Construct a Role from a dict with validation.

    Accepts both underscore and hyphen keys (YAML convention).
    Raises AudiaGenticError(VAL-ROL-001) if validation fails.
    """
    normalized = dict(data)
    if "required-capabilities" in normalized and "required_capabilities" not in normalized:
        normalized["required_capabilities"] = normalized.pop("required-capabilities")
    if "output-guidance" in normalized and "output_guidance" not in normalized:
        normalized["output_guidance"] = normalized.pop("output-guidance")
    if "runtime-tool-policy-ref" in normalized and "runtime_tool_policy_ref" not in normalized:
        normalized["runtime_tool_policy_ref"] = normalized.pop("runtime-tool-policy-ref")
    issues = validate_role(normalized)
    if issues:
        raise AudiaGenticError(
            code="VAL-ROL-001",
            kind="agents",
            message="role failed validation",
            details={"role_id": normalized.get("role_id"), "issues": issues},
        )
    return Role(
        role_id=str(normalized["role_id"]).strip(),
        instructions=str(normalized["instructions"]),
        required_capabilities=list(normalized.get("required_capabilities") or []),
        output_guidance=(
            str(normalized["output_guidance"]) if normalized.get("output_guidance") else None
        ),
        runtime_tool_policy_ref=(
            str(normalized["runtime_tool_policy_ref"])
            if normalized.get("runtime_tool_policy_ref")
            else None
        ),
        description=str(normalized.get("description") or "").strip(),
    )


def role_to_dict(role: Role) -> dict[str, Any]:
    """Serialize a Role to a dict for YAML round-trip."""
    return asdict(role)


class RoleStore:
    """In-memory store for roles with CRUD operations.

    Deliberately not composed (AS61 step 7 / ARCHITECTURE_STANDARDS.md §1
    "Composition candidates"): role definitions are stateless, project-local
    config -- read fresh, no connection, no shutdown -- exactly like
    project-local execution-profile resolution. There is nothing here with a
    lifetime worth owning.
    """

    def __init__(self, roles: list[Role] | None = None) -> None:
        self._roles: dict[str, Role] = {}
        if roles:
            for r in roles:
                self._roles[r.role_id] = r

    def get(self, role_id: str) -> Role:
        """Get a role by ID.

        Raises AudiaGenticError(RES-ROL-001) if not found.
        """
        role = self._roles.get(role_id)
        if role is None:
            raise AudiaGenticError(
                code="RES-ROL-001",
                kind="agents",
                message="role not found",
                details={"role_id": role_id},
            )
        return role

    def list_all(self) -> list[Role]:
        """Return all roles as a list."""
        return list(self._roles.values())

    def add(self, role: Role) -> None:
        """Add a role. Raises AudiaGenticError(RES-ROL-002) if ID already exists."""
        if role.role_id in self._roles:
            raise AudiaGenticError(
                code="RES-ROL-002",
                kind="agents",
                message="role ID already exists",
                details={"role_id": role.role_id},
            )
        self._roles[role.role_id] = role

    def remove(self, role_id: str) -> Role:
        """Remove and return a role. Raises AudiaGenticError(RES-ROL-001) if not found."""
        role = self.get(role_id)
        del self._roles[role_id]
        return role

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialize all roles to dicts."""
        return [role_to_dict(r) for r in self._roles.values()]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> RoleStore:
        """Construct a store from a list of role dicts."""
        roles = []
        for entry in data:
            try:
                roles.append(role_from_dict(entry))
            except AudiaGenticError:
                logger.warning("Skipping invalid role entry: %s", entry.get("role_id", "<unknown>"))
        return cls(roles)
