"""Agent profile data model and storage."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


@dataclass
class AgentProfile:
    """A named configuration that binds a provider to a specific model."""
    profile_id: str
    provider_id: str
    model_id: str
    model_alias: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    is_default: bool = False
    description: str = ""


def validate_profile(profile: dict[str, Any]) -> list[str]:
    """Validate a profile dict against the agent profile schema.

    Returns a list of issue strings. Empty list means valid.
    """
    issues: list[str] = []
    pid = profile.get("profile_id")
    if not pid or not isinstance(pid, str):
        issues.append("profile_id is required and must be a non-empty string")
    provider = profile.get("provider_id")
    if not provider or not isinstance(provider, str):
        issues.append("provider_id is required and must be a non-empty string")
    model = profile.get("model_id")
    if not model or not isinstance(model, str):
        issues.append("model_id is required and must be a non-empty string")
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
    return issues


def profile_from_dict(data: dict[str, Any]) -> AgentProfile:
    """Construct an AgentProfile from a dict with validation.

    Accepts both underscore and hyphen keys (YAML convention).
    Raises AudiaGenticError(VAL-AGP-001) if validation fails.
    """
    normalized = dict(data)
    if "is-default" in normalized and "is_default" not in normalized:
        normalized["is_default"] = normalized.pop("is-default")
    if "model-alias" in normalized and "model_alias" not in normalized:
        normalized["model_alias"] = normalized.pop("model-alias")
    issues = validate_profile(normalized)
    if issues:
        raise AudiaGenticError(
            code="VAL-AGP-001",
            kind="agents",
            message="agent profile failed validation",
            details={"profile_id": normalized.get("profile_id"), "issues": issues},
        )
    return AgentProfile(
        profile_id=str(normalized["profile_id"]).strip(),
        provider_id=str(normalized["provider_id"]).strip(),
        model_id=str(normalized["model_id"]).strip(),
        model_alias=str(normalized["model_alias"]).strip() if normalized.get("model_alias") else None,
        params=dict(normalized.get("params") or {}),
        is_default=bool(normalized.get("is_default", False)),
        description=str(normalized.get("description") or "").strip(),
    )


def profile_to_dict(profile: AgentProfile) -> dict[str, Any]:
    """Serialize an AgentProfile to a dict for YAML round-trip."""
    return asdict(profile)


class AgentProfilesStore:
    """In-memory store for agent profiles with CRUD operations."""

    def __init__(self, profiles: list[AgentProfile] | None = None) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        if profiles:
            for p in profiles:
                self._profiles[p.profile_id] = p

    def get(self, profile_id: str) -> AgentProfile:
        """Get a profile by ID.

        Raises AudiaGenticError(RES-AGP-001) if not found.
        """
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise AudiaGenticError(
                code="RES-AGP-001",
                kind="agents",
                message="agent profile not found",
                details={"profile_id": profile_id},
            )
        return profile

    def list_all(self) -> list[AgentProfile]:
        """Return all profiles as a list."""
        return list(self._profiles.values())

    def add(self, profile: AgentProfile) -> None:
        """Add a profile. Raises AudiaGenticError(RES-AGP-002) if ID already exists."""
        if profile.profile_id in self._profiles:
            raise AudiaGenticError(
                code="RES-AGP-002",
                kind="agents",
                message="agent profile ID already exists",
                details={"profile_id": profile.profile_id},
            )
        if profile.is_default:
            for existing in self._profiles.values():
                existing.is_default = False
        self._profiles[profile.profile_id] = profile

    def remove(self, profile_id: str) -> AgentProfile:
        """Remove and return a profile. Raises AudiaGenticError(RES-AGP-001) if not found."""
        profile = self.get(profile_id)
        del self._profiles[profile_id]
        return profile

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialize all profiles to dicts."""
        return [profile_to_dict(p) for p in self._profiles.values()]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> AgentProfilesStore:
        """Construct a store from a list of profile dicts."""
        profiles = []
        for entry in data:
            try:
                profiles.append(profile_from_dict(entry))
            except AudiaGenticError:
                logger.warning("Skipping invalid profile entry: %s", entry.get("profile_id", "<unknown>"))
        return cls(profiles)

    def get_default(self) -> AgentProfile | None:
        """Return the profile marked as default, or None."""
        for p in self._profiles.values():
            if p.is_default:
                return p
        return None
