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
