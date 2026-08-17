from __future__ import annotations

import pytest

from audiagentic.foundation.workflow import EvidencePolicy


def test_evidence_policy_combines_required_alternative_and_forbidden_facts():
    policy = EvidencePolicy.from_mapping(
        {
            "all-of": ["assistant-fresh", "text-present"],
            "any-of": ["completion-control", "done-marker"],
            "none-of": ["generating", "failure"],
        }
    )
    decision = policy.evaluate(
        {
            "assistant-fresh": True,
            "text-present": True,
            "completion-control": True,
            "generating": False,
            "failure": False,
        }
    )
    assert decision.satisfied
    assert decision.matched == {
        "assistant-fresh",
        "text-present",
        "completion-control",
    }


def test_evidence_policy_reports_missing_and_blocking_facts():
    policy = EvidencePolicy.from_mapping(
        {"all-of": ["text-present"], "none-of": ["failure"]}
    )
    decision = policy.evaluate({"failure": True})
    assert not decision.satisfied
    assert decision.missing == {"text-present"}
    assert decision.blocked_by == {"failure"}


@pytest.mark.parametrize(
    "value",
    [{}, {"unknown": []}, {"all-of": "fact"}, {"any-of": [""]}],
)
def test_invalid_evidence_policy_is_rejected(value):
    with pytest.raises(ValueError):
        EvidencePolicy.from_mapping(value)


def test_any_of_groups_satisfied_when_either_whole_group_matches():
    """A policy with two alternative corroborating-evidence groups is
    satisfied if EITHER group's facts are all true -- not just any single
    fact across groups. This is the disjunction-of-conjunctions shape
    gpt-auto's GP32 fix needed: two independently-valid ways to prove the
    same underlying fact, so one group's selector breaking doesn't make
    the whole policy permanently unsatisfiable."""
    policy = EvidencePolicy.from_mapping(
        {
            "all-of": ["assistant-fresh"],
            "any-of-groups": [
                ["completion-control", "more-actions-menu"],
                ["completion-control", "message-finalized"],
            ],
        }
    )
    # Only the first group's second fact is true -- first group fully
    # satisfied, second group is not. Must still be satisfied overall.
    decision = policy.evaluate(
        {
            "assistant-fresh": True,
            "completion-control": True,
            "more-actions-menu": True,
            "message-finalized": False,
        }
    )
    assert decision.satisfied
    assert decision.matched == {
        "assistant-fresh",
        "completion-control",
        "more-actions-menu",
    }


def test_any_of_groups_only_policy_needs_no_other_condition():
    """code review, 2026-08-17: a policy consisting of ONLY any-of-groups
    (no all-of/any-of/none-of) must be a valid, constructible policy."""
    policy = EvidencePolicy.from_mapping({"any-of-groups": [["a", "b"]]})
    assert policy.evaluate({"a": True, "b": True}).satisfied
    assert not policy.evaluate({"a": True, "b": False}).satisfied


def test_any_of_groups_reports_which_groups_matched():
    """code review, 2026-08-17: matched/missing alone collapse group
    structure -- a caller cannot tell which group(s) actually satisfied
    the policy. matched_groups preserves that, including when MULTIPLE
    groups are simultaneously satisfied."""
    policy = EvidencePolicy.from_mapping(
        {"any-of-groups": [["a", "b"], ["c", "d"]]}
    )
    only_first = policy.evaluate({"a": True, "b": True, "c": False, "d": False})
    assert only_first.matched_groups == (frozenset({"a", "b"}),)

    both = policy.evaluate({"a": True, "b": True, "c": True, "d": True})
    assert set(both.matched_groups) == {frozenset({"a", "b"}), frozenset({"c", "d"})}
    assert len(both.matched_groups) == 2


def test_any_of_groups_reports_missing_facts_per_group():
    """code review, 2026-08-17: when NO group is satisfied, missing_by_group
    lets a caller report e.g. 'group 0 missing: b' vs 'group 1 missing: c,
    d' instead of only a flattened set with no group structure."""
    policy = EvidencePolicy.from_mapping(
        {"any-of-groups": [["a", "b"], ["c", "d"]]}
    )
    decision = policy.evaluate({"a": True, "b": False, "c": False, "d": False})
    assert not decision.satisfied
    assert decision.matched_groups == ()
    assert decision.missing_by_group == (frozenset({"b"}), frozenset({"c", "d"}))


def test_any_of_groups_not_satisfied_when_no_group_fully_matches():
    """A partial match spanning across two groups (one fact from each)
    must not satisfy the policy -- each group is evaluated as a whole
    conjunction, not merged into one big any-of."""
    policy = EvidencePolicy.from_mapping(
        {
            "any-of-groups": [
                ["completion-control", "more-actions-menu"],
                ["completion-control", "message-finalized"],
            ],
        }
    )
    decision = policy.evaluate({"completion-control": True, "more-actions-menu": False, "message-finalized": False})
    assert not decision.satisfied


def test_any_of_groups_combines_with_all_of_and_none_of():
    policy = EvidencePolicy.from_mapping(
        {
            "all-of": ["text-present"],
            "none-of": ["error-page"],
            "any-of-groups": [["witness-a", "witness-b"]],
        }
    )
    blocked = policy.evaluate(
        {"text-present": True, "witness-a": True, "witness-b": True, "error-page": True}
    )
    assert not blocked.satisfied
    assert blocked.blocked_by == {"error-page"}

    ok = policy.evaluate(
        {"text-present": True, "witness-a": True, "witness-b": True, "error-page": False}
    )
    assert ok.satisfied


@pytest.mark.parametrize(
    "value",
    [
        {"any-of-groups": "not-a-list"},
        {"any-of-groups": [[]]},
        {"any-of-groups": [["ok"], "not-a-list"]},
        {"any-of-groups": [[""]]},
    ],
)
def test_invalid_any_of_groups_is_rejected(value):
    with pytest.raises(ValueError):
        EvidencePolicy.from_mapping(value)
