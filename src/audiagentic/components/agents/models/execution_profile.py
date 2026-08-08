"""Execution profile data model and storage."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


@dataclass
class ExecutionProfile:
    """A named configuration that binds a provider to a set of acceptable
    model instances (AS105/AS101 v2 -- replaces the single model_id).

    ``instances`` names one or more model-sources.yaml source-ids the
    profile accepts; free-instance dispatch binds to whichever has spare
    capacity at dispatch time, never at admission.
    """
    profile_id: str
    provider_id: str
    instances: tuple[str, ...]
    model_alias: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    is_default: bool = False
    description: str = ""
    # AS82: optional AS29 session surface this profile launches through.
    # Absent means provider default -- not an error. AS29 remains the sole
    # surface-capability authority; this field selects, it does not describe.
    surface_id: str | None = None


def validate_execution_profile(profile: dict[str, Any]) -> list[str]:
    """Validate a profile dict against the execution profile schema.

    Returns a list of issue strings. Empty list means valid.
    """
    issues: list[str] = []
    pid = profile.get("profile_id")
    if not pid or not isinstance(pid, str):
        issues.append("profile_id is required and must be a non-empty string")
    provider = profile.get("provider_id")
    if not provider or not isinstance(provider, str):
        issues.append("provider_id is required and must be a non-empty string")
    instances = profile.get("instances")
    if (
        not instances
        or not isinstance(instances, (list, tuple))
        or not all(isinstance(i, str) and i.strip() for i in instances)
    ):
        issues.append("instances is required and must be a non-empty list of non-empty strings")
    if "model_alias" in profile and profile["model_alias"] is not None:
        if not isinstance(profile["model_alias"], str):
            issues.append("model_alias must be a string or null")
    if "params" in profile and profile["params"] is not None:
        if not isinstance(profile["params"], dict):
            issues.append("params must be a mapping or null")
    if "is_default" in profile and not isinstance(profile["is_default"], bool):
        issues.append("is_default must be a boolean")
    if "description" in profile and profile["description"] is not None:
        if not isinstance(profile["description"], str):
            issues.append("description must be a string or null")
    if "surface_id" in profile and profile["surface_id"] is not None:
        if not isinstance(profile["surface_id"], str) or not profile["surface_id"].strip():
            issues.append("surface_id must be a non-empty string or null")
    return issues


def execution_profile_from_dict(data: dict[str, Any]) -> ExecutionProfile:
    """Construct an ExecutionProfile from a dict with validation.

    Accepts both underscore and hyphen keys (YAML convention).
    Raises AudiaGenticError(VAL-EXP-001) if validation fails.
    """
    normalized = dict(data)
    if "is-default" in normalized and "is_default" not in normalized:
        normalized["is_default"] = normalized.pop("is-default")
    if "model-alias" in normalized and "model_alias" not in normalized:
        normalized["model_alias"] = normalized.pop("model-alias")
    if "surface-id" in normalized and "surface_id" not in normalized:
        normalized["surface_id"] = normalized.pop("surface-id")
    issues = validate_execution_profile(normalized)
    if issues:
        raise AudiaGenticError(
            code="VAL-EXP-001",
            kind="agents",
            message="execution profile failed validation",
            details={"profile_id": normalized.get("profile_id"), "issues": issues},
        )
    return ExecutionProfile(
        profile_id=str(normalized["profile_id"]).strip(),
        provider_id=str(normalized["provider_id"]).strip(),
        instances=tuple(str(i).strip() for i in normalized["instances"]),
        model_alias=str(normalized["model_alias"]).strip() if normalized.get("model_alias") else None,
        params=dict(normalized.get("params") or {}),
        is_default=bool(normalized.get("is_default", False)),
        description=str(normalized.get("description") or "").strip(),
        surface_id=str(normalized["surface_id"]).strip() if normalized.get("surface_id") else None,
    )


def execution_profile_to_dict(profile: ExecutionProfile) -> dict[str, Any]:
    """Serialize an ExecutionProfile to a dict for YAML round-trip."""
    data = asdict(profile)
    data["instances"] = list(profile.instances)
    return data


class ExecutionProfileStore:
    """In-memory store for execution profiles with CRUD operations."""

    def __init__(self, profiles: list[ExecutionProfile] | None = None) -> None:
        self._profiles: dict[str, ExecutionProfile] = {}
        if profiles:
            for p in profiles:
                self._profiles[p.profile_id] = p

    def get(self, profile_id: str) -> ExecutionProfile:
        """Get a profile by ID.

        Raises AudiaGenticError(RES-EXP-001) if not found.
        """
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise AudiaGenticError(
                code="RES-EXP-001",
                kind="agents",
                message="execution profile not found",
                details={"profile_id": profile_id},
            )
        return profile

    def list_all(self) -> list[ExecutionProfile]:
        """Return all profiles as a list."""
        return list(self._profiles.values())

    def add(self, profile: ExecutionProfile) -> None:
        """Add a profile. Raises AudiaGenticError(RES-EXP-002) if ID already exists."""
        if profile.profile_id in self._profiles:
            raise AudiaGenticError(
                code="RES-EXP-002",
                kind="agents",
                message="execution profile ID already exists",
                details={"profile_id": profile.profile_id},
            )
        if profile.is_default:
            for existing in self._profiles.values():
                existing.is_default = False
        self._profiles[profile.profile_id] = profile

    def remove(self, profile_id: str) -> ExecutionProfile:
        """Remove and return a profile. Raises AudiaGenticError(RES-EXP-001) if not found."""
        profile = self.get(profile_id)
        del self._profiles[profile_id]
        return profile

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialize all profiles to dicts."""
        return [execution_profile_to_dict(p) for p in self._profiles.values()]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> ExecutionProfileStore:
        """Construct a store from a list of profile dicts."""
        profiles = []
        for entry in data:
            try:
                profiles.append(execution_profile_from_dict(entry))
            except AudiaGenticError:
                logger.warning("Skipping invalid profile entry: %s", entry.get("profile_id", "<unknown>"))
        return cls(profiles)

    def get_default(self) -> ExecutionProfile | None:
        """Return the profile marked as default, or None."""
        for p in self._profiles.values():
            if p.is_default:
                return p
        return None
