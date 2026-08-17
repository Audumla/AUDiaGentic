from __future__ import annotations

from dataclasses import dataclass

from audiagentic.components.providers.adapters.gpt_auto.observation_engine import (
    EvidenceCapability,
    Observation,
    ObservationOutcome,
    ObservationState,
    ObservationTracker,
)

NONE = EvidenceCapability.NONE
PROGRESS = EvidenceCapability.PROGRESS
SOFT = EvidenceCapability.SOFT_LIVENESS
WITNESS = EvidenceCapability.TERMINAL_WITNESS


@dataclass
class _Policy:
    start_bound_seconds: float = 15.0
    progress_lease_seconds: float = 300.0
    soft_grace_cap_seconds: float = 60.0
    candidate_stability_window_seconds: float = 6.0
    candidate_max_verification_window_seconds: float = 30.0
    suspect_grace_seconds: float = 60.0
    absolute_ceiling_seconds: float = 1200.0


def _obs(caps=NONE, *, candidate=False, verified=False) -> Observation:
    return Observation(capabilities=caps, terminal_candidate=candidate, terminal_verified_ok=verified)


def test_reaches_verified_terminal_on_stable_witnessed_candidate():
    tracker = ObservationTracker(policy=_Policy(), now=0.0)
    tracker.advance(_obs(PROGRESS), now=1.0)
    assert tracker.state is ObservationState.ACTIVE
    outcome = tracker.advance(_obs(WITNESS, candidate=True, verified=True), now=2.0)
    assert outcome is None
    assert tracker.state is ObservationState.CANDIDATE_TERMINAL
    outcome = tracker.advance(_obs(WITNESS, candidate=True, verified=True), now=9.0)
    assert outcome is ObservationOutcome.VERIFIED_TERMINAL


def test_flapping_soft_liveness_widget_cannot_hang_forever():
    """The exact hole the reviewer found: a widget re-triggering SOFT_LIVENESS
    on every poll must not indefinitely postpone SUSPECT_STALLED by
    repeatedly resetting the real progress lease."""
    policy = _Policy(progress_lease_seconds=300.0, soft_grace_cap_seconds=60.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    tracker.advance(_obs(SOFT), now=1.0)
    assert tracker.state is ObservationState.ACTIVE

    outcome = None
    t = 1.0
    while t < 1000.0:
        t += 10.0
        outcome = tracker.advance(_obs(SOFT), now=t)
        if outcome is not None:
            break

    assert outcome is ObservationOutcome.UNRESOLVED_STALL
    # must stall out at progress_lease + soft_grace_cap (+ suspect_grace),
    # nowhere near the 1000s of continuous flapping fed in
    assert t < policy.progress_lease_seconds + policy.soft_grace_cap_seconds + policy.suspect_grace_seconds + 20


def test_progress_evidence_resets_lease_and_repeated_progress_never_stalls():
    policy = _Policy(progress_lease_seconds=10.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    outcome = None
    for t in range(1, 200, 5):
        outcome = tracker.advance(_obs(PROGRESS), now=float(t))
        assert outcome is None
    assert tracker.state is ObservationState.ACTIVE


def test_terminal_witness_alone_cannot_reopen_a_candidate_but_progress_can():
    policy = _Policy(candidate_stability_window_seconds=6.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    tracker.advance(_obs(PROGRESS), now=1.0)
    tracker.advance(_obs(WITNESS, candidate=True), now=2.0)
    assert tracker.state is ObservationState.CANDIDATE_TERMINAL

    # a soft-liveness/witness-only observation must not reopen the candidate
    tracker.advance(_obs(SOFT | WITNESS, candidate=True), now=3.0)
    assert tracker.state is ObservationState.CANDIDATE_TERMINAL

    # but new PROGRESS must reopen it
    tracker.advance(_obs(PROGRESS), now=4.0)
    assert tracker.state is ObservationState.ACTIVE


def test_candidate_terminal_resets_immediately_when_witness_vanishes():
    """GP40 (code review, 2026-08-17): merely losing terminal_candidate used
    to be silently ignored -- the candidate_entered_at timer kept running
    underneath, so a real sequence like "terminal evidence, generation
    quietly resumes without changing text (no PROGRESS), terminal evidence
    flickers absent then true again" would satisfy candidate_stability_
    window_seconds as if the candidate had been continuously eligible the
    whole time, when it was not. Losing terminal_candidate must discard the
    candidate immediately and require a fresh one to re-arm the window --
    not let a stale clock survive to expire into SUSPECT_STALLED later."""
    policy = _Policy(candidate_stability_window_seconds=5.0, candidate_max_verification_window_seconds=10.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    tracker.advance(_obs(PROGRESS), now=1.0)
    tracker.advance(_obs(WITNESS, candidate=True), now=2.0)
    assert tracker.state is ObservationState.CANDIDATE_TERMINAL

    outcome = tracker.advance(_obs(NONE, candidate=False), now=3.0)
    assert outcome is None
    assert tracker.state is ObservationState.ACTIVE
    assert tracker.clock.candidate_entered_at is None
    assert tracker.clock.candidate_generation is None

    # a fresh terminal observation re-arms a NEW window from now, not from
    # the original (discarded) candidate_entered_at
    outcome = tracker.advance(_obs(WITNESS, candidate=True), now=4.0)
    assert outcome is None
    assert tracker.state is ObservationState.CANDIDATE_TERMINAL
    assert tracker.clock.candidate_entered_at == 4.0
    outcome = tracker.advance(_obs(WITNESS, candidate=True, verified=True), now=8.9)
    assert outcome is None, "must not verify before a fresh 5s window elapses from the reset"
    outcome = tracker.advance(_obs(WITNESS, candidate=True, verified=True), now=9.1)
    assert outcome is ObservationOutcome.VERIFIED_TERMINAL


def test_suspect_stalled_recovers_to_candidate_terminal_on_weak_witness_reappearing():
    """Weak evidence cannot claim progress, but it can still participate in
    a legitimate terminal proof once already suspect."""
    policy = _Policy(suspect_grace_seconds=30.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    tracker.state = ObservationState.SUSPECT_STALLED
    tracker.clock.suspect_entered_at = 0.0
    tracker.clock.phase_started_at = 0.0

    outcome = tracker.advance(_obs(WITNESS, candidate=True), now=5.0)
    assert outcome is None
    assert tracker.state is ObservationState.CANDIDATE_TERMINAL


def test_suspect_stalled_recovers_to_active_on_real_progress():
    policy = _Policy(suspect_grace_seconds=30.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    tracker.state = ObservationState.SUSPECT_STALLED
    tracker.clock.suspect_entered_at = 0.0
    tracker.clock.phase_started_at = 0.0

    outcome = tracker.advance(_obs(PROGRESS), now=5.0)
    assert outcome is None
    assert tracker.state is ObservationState.ACTIVE


def test_absolute_ceiling_produces_budget_exhausted_even_with_continuous_progress():
    """A pathological slow-trickle stream (progress just often enough to
    never stall) must still terminate at the absolute ceiling."""
    policy = _Policy(progress_lease_seconds=300.0, absolute_ceiling_seconds=120.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    outcome = None
    for t in range(1, 300, 5):
        outcome = tracker.advance(_obs(PROGRESS), now=float(t))
        if outcome is not None:
            break
    assert outcome is ObservationOutcome.BUDGET_EXHAUSTED


def test_awaiting_evidence_stalls_if_absolutely_nothing_is_ever_observed():
    policy = _Policy(start_bound_seconds=15.0, suspect_grace_seconds=10.0)
    tracker = ObservationTracker(policy=policy, now=0.0)
    outcome = tracker.advance(_obs(NONE), now=16.0)
    assert outcome is None
    assert tracker.state is ObservationState.SUSPECT_STALLED
    outcome = tracker.advance(_obs(NONE), now=27.0)
    assert outcome is ObservationOutcome.UNRESOLVED_STALL
