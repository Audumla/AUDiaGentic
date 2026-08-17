"""Pure, provider-neutral evidence policy evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidencePolicy:
    """A declarative boolean policy over named observed facts.

    all_of/any_of/none_of form one flat conjunction, same as always.
    any_of_groups adds a disjunction of AND-groups on top: if present, at
    least one whole group's facts must ALL be true. This exists so a
    single corroborating-evidence requirement can have more than one
    independently-valid way to be satisfied for the SAME underlying
    state -- e.g. two different DOM signal pairs that each separately
    prove the same thing is true right now.

    Precisely what this does and does not buy you (code review,
    2026-08-17): it solves "multiple alternative valid shapes of the same
    evidence." It does NOT automatically solve "one renderer variant's
    signals broke, fall back to another renderer's signals" -- that only
    works if the groups genuinely describe alternative observations of
    the SAME state. If the groups instead describe DIFFERENT states (e.g.
    one group is only ever true for renderer A's turns, another only for
    renderer B's), losing renderer A's signals does not get rescued by
    renderer B's group; renderer A's turns simply have no satisfiable
    group left, same as before any_of_groups existed. (gpt-auto's
    response-complete is exactly this second case: one group per response
    rendering variant, not multiple alternatives for one variant --
    ChatGPT removing message-finalized broke response-complete for
    standard-bubble turns specifically; adding the canvas group did not
    "rescue" that, it only added coverage for a DIFFERENT, previously-
    uncovered variant.)"""

    all_of: frozenset[str] = frozenset()
    any_of: frozenset[str] = frozenset()
    none_of: frozenset[str] = frozenset()
    any_of_groups: tuple[frozenset[str], ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EvidencePolicy:
        unknown = set(value) - {"all-of", "any-of", "none-of", "any-of-groups"}
        if unknown:
            raise ValueError(f"unknown evidence policy keys: {sorted(unknown)}")
        raw_groups = value.get("any-of-groups", [])
        if not isinstance(raw_groups, list) or any(
            not isinstance(group, list) or not group for group in raw_groups
        ):
            raise ValueError("any-of-groups must be a list of non-empty fact-name lists")
        groups = tuple(_names(group, "any-of-groups") for group in raw_groups)
        policy = cls(
            all_of=_names(value.get("all-of", []), "all-of"),
            any_of=_names(value.get("any-of", []), "any-of"),
            none_of=_names(value.get("none-of", []), "none-of"),
            any_of_groups=groups,
        )
        if not (policy.all_of or policy.any_of or policy.none_of or policy.any_of_groups):
            raise ValueError("evidence policy must contain at least one condition")
        return policy

    def evaluate(self, facts: Mapping[str, bool]) -> EvidenceDecision:
        true_facts = frozenset(name for name, present in facts.items() if present)
        missing_all = self.all_of - true_facts
        matched_any = self.any_of & true_facts
        blocked_by = self.none_of & true_facts
        matched_groups = tuple(group for group in self.any_of_groups if group <= true_facts)
        groups_ok = not self.any_of_groups or bool(matched_groups)
        satisfied = (
            not missing_all
            and not blocked_by
            and (not self.any_of or bool(matched_any))
            and groups_ok
        )
        matched_group_facts: frozenset[str] = frozenset().union(*matched_groups) if matched_groups else frozenset()
        # code review, 2026-08-17: matched/missing alone collapse group
        # structure -- a caller could see facts A, B, C, D matched but not
        # tell whether the satisfying groups were [A,B]+[C,D] or something
        # else, and when NO group matched, could not tell "group 0 is
        # missing B" from "group 1 is missing D". missing_by_group
        # preserves that per-group detail, in any_of_groups' own order,
        # for exactly the debugging any_of_groups exists to make possible.
        missing_by_group = tuple(group - true_facts for group in self.any_of_groups)
        return EvidenceDecision(
            satisfied=satisfied,
            matched=frozenset((self.all_of & true_facts) | matched_any | matched_group_facts),
            missing=missing_all,
            blocked_by=blocked_by,
            matched_groups=matched_groups,
            missing_by_group=missing_by_group,
        )


@dataclass(frozen=True)
class EvidenceDecision:
    satisfied: bool
    matched: frozenset[str]
    missing: frozenset[str]
    blocked_by: frozenset[str]
    # Which any_of_groups entries were fully satisfied (may be more than
    # one if several groups matched simultaneously); empty if any_of_groups
    # was empty, or if none matched.
    matched_groups: tuple[frozenset[str], ...] = ()
    # Per-group leftover facts, in any_of_groups' own order -- an empty
    # frozenset at index i means group i was fully satisfied. Lets a
    # caller report e.g. "group 0 missing: more-actions-menu" instead of
    # only a flattened, group-structure-free set of missing facts.
    missing_by_group: tuple[frozenset[str], ...] = ()


def _names(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field} must be a list of non-empty fact names")
    return frozenset(value)


__all__ = ["EvidenceDecision", "EvidencePolicy"]
