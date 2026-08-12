"""Pure, provider-neutral evidence policy evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidencePolicy:
    """A declarative boolean policy over named observed facts."""

    all_of: frozenset[str] = frozenset()
    any_of: frozenset[str] = frozenset()
    none_of: frozenset[str] = frozenset()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EvidencePolicy:
        unknown = set(value) - {"all-of", "any-of", "none-of"}
        if unknown:
            raise ValueError(f"unknown evidence policy keys: {sorted(unknown)}")
        policy = cls(
            all_of=_names(value.get("all-of", []), "all-of"),
            any_of=_names(value.get("any-of", []), "any-of"),
            none_of=_names(value.get("none-of", []), "none-of"),
        )
        if not (policy.all_of or policy.any_of or policy.none_of):
            raise ValueError("evidence policy must contain at least one condition")
        return policy

    def evaluate(self, facts: Mapping[str, bool]) -> EvidenceDecision:
        true_facts = frozenset(name for name, present in facts.items() if present)
        missing_all = self.all_of - true_facts
        matched_any = self.any_of & true_facts
        blocked_by = self.none_of & true_facts
        satisfied = not missing_all and not blocked_by and (
            not self.any_of or bool(matched_any)
        )
        return EvidenceDecision(
            satisfied=satisfied,
            matched=frozenset((self.all_of & true_facts) | matched_any),
            missing=missing_all,
            blocked_by=blocked_by,
        )


@dataclass(frozen=True)
class EvidenceDecision:
    satisfied: bool
    matched: frozenset[str]
    missing: frozenset[str]
    blocked_by: frozenset[str]


def _names(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field} must be a list of non-empty fact names")
    return frozenset(value)


__all__ = ["EvidenceDecision", "EvidencePolicy"]
