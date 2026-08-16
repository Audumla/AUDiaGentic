"""Shared, activity-driven observation state machine for gpt-auto's turn
lifecycle phases (submission-proof, response-completion).

Design (GP07, formalized 2026-08-16 after a live false-negative and a real
gpt-auto-reviewer design critique): replaces fixed action-start deadlines
with progress-aware clocks, and gives evidence a *capability* rather than a
single trust level -- one observation can carry more than one.

- PROGRESS: authoritative, causally-scoped content change (new/changed
  current-turn text, a new message id, the submitted prompt appearing as a
  new user message). Resets the real inactivity clock, bumps a monotonic
  progress_generation, reopens a terminal candidate, recovers from a stall.
- SOFT_LIVENESS: an inferred UI widget's self-reported state (a stop/submit
  button, a streaming/thinking/busy CSS class). Grants at most one bounded
  extension anchored to the *original* lease deadline -- never a repeated
  reset -- and otherwise has no authority. A widget already proven to lie
  (stop-control sticking after real completion) must never gate a failure
  decision, including indirectly by renewing the clock that gates it.
- TERMINAL_WITNESS: corroborating evidence a response is done (a completion
  affordance, a markdown-renderer "last node" marker). Can enter/verify a
  terminal candidate; cannot reopen one; does not count as progress.

Outcomes deliberately separate "proved this failed" from "failed to prove
what happened" -- conflating them risks a duplicate-submission bug on
retry (the exact failure mode a stale fixed deadline created live).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Flag, StrEnum, auto
from typing import Protocol


class EvidenceCapability(Flag):
    NONE = 0
    PROGRESS = auto()
    SOFT_LIVENESS = auto()
    TERMINAL_WITNESS = auto()


class ObservationState(StrEnum):
    AWAITING_EVIDENCE = "awaiting-evidence"
    ACTIVE = "active"
    CANDIDATE_TERMINAL = "candidate-terminal"
    SUSPECT_STALLED = "suspect-stalled"
    DONE = "done"


class ObservationOutcome(StrEnum):
    VERIFIED_TERMINAL = "verified-terminal"
    UNRESOLVED_STALL = "unresolved-stall"
    BUDGET_EXHAUSTED = "budget-exhausted"


@dataclass(frozen=True)
class Observation:
    """One phase-specific classification of a raw snapshot/result pair."""

    capabilities: EvidenceCapability
    terminal_candidate: bool
    terminal_verified_ok: bool = False


class ObservationPolicy(Protocol):
    start_bound_seconds: float
    progress_lease_seconds: float
    soft_grace_cap_seconds: float
    candidate_stability_window_seconds: float
    candidate_max_verification_window_seconds: float
    suspect_grace_seconds: float
    absolute_ceiling_seconds: float


@dataclass
class ObservationClock:
    phase_started_at: float
    last_conclusive_progress_at: float | None = None
    last_soft_activity_at: float | None = None
    soft_grace_deadline: float | None = None
    progress_generation: int = 0
    candidate_entered_at: float | None = None
    candidate_generation: int | None = None
    suspect_entered_at: float | None = None


@dataclass
class ObservationTracker:
    """Stateful driver: feed observations, get a state and (eventually) an
    outcome. One instance per awaited phase (one per turn's submission-proof
    wait, one per turn's response-completion wait)."""

    policy: ObservationPolicy
    now: float
    clock: ObservationClock = field(init=False)
    state: ObservationState = field(init=False, default=ObservationState.AWAITING_EVIDENCE)

    def __post_init__(self) -> None:
        self.clock = ObservationClock(phase_started_at=self.now)

    def _progress_lease_deadline(self) -> float:
        base = self.clock.last_conclusive_progress_at or self.clock.phase_started_at
        deadline = base + self.policy.progress_lease_seconds
        if self.clock.soft_grace_deadline is not None:
            deadline = max(deadline, self.clock.soft_grace_deadline)
        return deadline

    def advance(self, observation: Observation, now: float) -> ObservationOutcome | None:
        """Feed one new observation. Returns an outcome once reached, else None."""
        self.now = now
        clock = self.clock
        caps = observation.capabilities

        if EvidenceCapability.PROGRESS in caps:
            clock.last_conclusive_progress_at = now
            clock.progress_generation += 1
            clock.soft_grace_deadline = None
        elif EvidenceCapability.SOFT_LIVENESS in caps:
            clock.last_soft_activity_at = now
            if clock.soft_grace_deadline is None:
                base_deadline = (
                    clock.last_conclusive_progress_at or clock.phase_started_at
                ) + self.policy.progress_lease_seconds
                clock.soft_grace_deadline = base_deadline + self.policy.soft_grace_cap_seconds

        if self.state is ObservationState.AWAITING_EVIDENCE:
            if caps is not EvidenceCapability.NONE or observation.terminal_candidate:
                self.state = ObservationState.ACTIVE
            elif now - clock.phase_started_at >= self.policy.start_bound_seconds:
                self.state = ObservationState.SUSPECT_STALLED
                clock.suspect_entered_at = now

        if self.state is ObservationState.ACTIVE:
            if observation.terminal_candidate:
                self.state = ObservationState.CANDIDATE_TERMINAL
                clock.candidate_entered_at = now
                clock.candidate_generation = clock.progress_generation
            elif now >= self._progress_lease_deadline():
                self.state = ObservationState.SUSPECT_STALLED
                clock.suspect_entered_at = now

        elif self.state is ObservationState.CANDIDATE_TERMINAL:
            assert clock.candidate_entered_at is not None
            if (
                EvidenceCapability.PROGRESS in caps
                and clock.progress_generation != clock.candidate_generation
            ):
                self.state = ObservationState.ACTIVE
                clock.candidate_entered_at = None
                clock.candidate_generation = None
            elif now - clock.candidate_entered_at >= self.policy.candidate_stability_window_seconds:
                if (
                    observation.terminal_verified_ok
                    and clock.progress_generation == clock.candidate_generation
                ):
                    self.state = ObservationState.DONE
                    return ObservationOutcome.VERIFIED_TERMINAL
                if (
                    now - clock.candidate_entered_at
                    >= self.policy.candidate_max_verification_window_seconds
                ):
                    self.state = ObservationState.SUSPECT_STALLED
                    clock.suspect_entered_at = now
                    clock.candidate_entered_at = None
                    clock.candidate_generation = None

        elif self.state is ObservationState.SUSPECT_STALLED:
            assert clock.suspect_entered_at is not None
            if EvidenceCapability.PROGRESS in caps:
                self.state = ObservationState.ACTIVE
                clock.suspect_entered_at = None
            elif observation.terminal_candidate:
                self.state = ObservationState.CANDIDATE_TERMINAL
                clock.candidate_entered_at = now
                clock.candidate_generation = clock.progress_generation
                clock.suspect_entered_at = None
            elif now - clock.suspect_entered_at >= self.policy.suspect_grace_seconds:
                self.state = ObservationState.DONE
                return ObservationOutcome.UNRESOLVED_STALL

        if now - clock.phase_started_at >= self.policy.absolute_ceiling_seconds:
            self.state = ObservationState.DONE
            return ObservationOutcome.BUDGET_EXHAUSTED

        return None


__all__ = [
    "EvidenceCapability",
    "Observation",
    "ObservationClock",
    "ObservationOutcome",
    "ObservationPolicy",
    "ObservationState",
    "ObservationTracker",
]
