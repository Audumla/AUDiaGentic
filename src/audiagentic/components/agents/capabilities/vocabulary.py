"""Small explicit vocabulary seam; additions must be deliberate."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import CapabilityRequirementId, LaunchContribution


@dataclass(frozen=True, slots=True)
class CapabilityVocabulary:
    launches: dict[CapabilityRequirementId, LaunchContribution]
    evidence_only: frozenset[CapabilityRequirementId] = frozenset()

    def resolve(self, requirement_id: CapabilityRequirementId) -> LaunchContribution:
        if requirement_id in self.evidence_only:
            raise ValueError(f"evidence-only capability cannot be a Role requirement: {requirement_id.value}")
        try:
            return self.launches[requirement_id]
        except KeyError as exc:
            raise ValueError(f"unknown capability requirement: {requirement_id.value}") from exc
