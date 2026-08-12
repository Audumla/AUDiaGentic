"""AS91 tests for proven owned-turn death classification only."""

from __future__ import annotations

import pytest

from audiagentic.components.agents.gateway.session.orphan import (
    OwnedTurnLiveness,
    is_proven_owned_turn_dead,
)
from audiagentic.foundation.system.adopted_process import (
    AdoptedChild,
    OwnershipCheckResult,
)
from audiagentic.foundation.system.managed_process import ProcessEvidence


def _child(*, external: bool = False) -> AdoptedChild:
    return AdoptedChild(
        evidence=ProcessEvidence(
            pid=4242,
            scope="session-child",
            command_fingerprint="sha256:" + "a" * 64,
            ownership_proof_kind="creation-identity",
            owner_epoch="owner-epoch",
            creation_identity="created:4242",
        ),
        is_external=external,
    )


def _handle(**changes) -> OwnedTurnLiveness:
    values = {
        "request_id": "req_turn_001",
        "turn_task": object(),
        "turn_active": True,
        "adopted_child": _child(),
        "closing_deadline": 100.0,
        "last_event_clock": 99.0,
    }
    values.update(changes)
    return OwnedTurnLiveness(**values)


PROVEN_DEAD = OwnershipCheckResult(
    owned=False, alive=False, observed=None, refusal_reason="process-dead"
)


def test_proven_dead_owned_active_turn_is_the_only_positive_case() -> None:
    assert is_proven_owned_turn_dead(_handle(), PROVEN_DEAD, now=101.0) is True


@pytest.mark.parametrize(
    "observation",
    [
        None,
        OwnershipCheckResult(owned=False, alive=True, observed=None, refusal_reason="unobservable"),
        OwnershipCheckResult(owned=True, alive=True, observed=object()),
    ],
)
def test_unknown_or_live_child_evidence_is_conservatively_not_dead(observation) -> None:
    assert is_proven_owned_turn_dead(_handle(), observation, now=101.0) is False


def test_external_child_is_never_an_owned_turn_orphan() -> None:
    assert is_proven_owned_turn_dead(_handle(adopted_child=_child(external=True)), PROVEN_DEAD, now=101.0) is False


def test_pid_reuse_or_identity_mismatch_is_not_death_proof() -> None:
    reused_pid = OwnershipCheckResult(
        owned=False,
        alive=True,
        observed=object(),
        refusal_reason="ownership-mismatch",
    )
    assert is_proven_owned_turn_dead(_handle(), reused_pid, now=101.0) is False


def test_silence_or_expired_closing_deadline_alone_is_not_death_proof() -> None:
    silent = _handle(last_event_clock=0.0, closing_deadline=1.0)
    assert is_proven_owned_turn_dead(silent, None, now=10_000.0) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": None},
        {"turn_task": None},
        {"turn_active": False},
        {"adopted_child": None},
    ],
)
def test_missing_current_owned_turn_fact_is_not_death_proof(changes) -> None:
    assert is_proven_owned_turn_dead(_handle(**changes), PROVEN_DEAD, now=101.0) is False
