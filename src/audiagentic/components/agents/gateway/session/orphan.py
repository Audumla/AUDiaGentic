"""AS91's conservative, side-effect-free owned-turn death predicate.

This module deliberately makes no lifecycle transition, lock release, task
cancellation, or process signal.  It turns foundation's identity observation
into the one narrow fact a future owning session task may consume: its current
internally-owned child is positively observed dead.  Every other observation
is UNKNOWN for cleanup purposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.system.adopted_process import (
    AdoptedChild,
    OwnershipCheckResult,
)


@dataclass(frozen=True)
class OwnedTurnLiveness:
    """The minimum live-turn facts required to classify orphan death.

    ``turn_task`` intentionally remains opaque: the predicate only needs to
    know that the owning task exists.  Its ``finally`` block remains the sole
    place that may release the turn lock, capacity reservation, or accounting.
    ``last_event_clock`` is carried to make the non-use of silence explicit.
    """

    request_id: str | None
    turn_task: Any | None
    turn_active: bool
    adopted_child: AdoptedChild | None
    closing_deadline: float | None
    last_event_clock: float | None = None


def is_proven_owned_turn_dead(
    handle: OwnedTurnLiveness,
    observation: OwnershipCheckResult | None,
    now: float,
) -> bool:
    """Return true only for positive death of a current owned child turn.

    ``now``, closing deadlines, and event silence are intentionally not
    evidence of death.  A PID-reused or unobservable child remains false even
    where the process is suspected unhealthy.  This function is pure: callers
    supply the observation produced by ``observe_child`` and decide any action
    through the existing owning task/lifecycle path.
    """
    _ = now  # Deadlines are cleanup policy, never evidence of process death.
    if not handle.turn_active or not handle.request_id or handle.turn_task is None:
        return False
    child = handle.adopted_child
    if child is None or child.is_external:
        return False
    if observation is None:
        return False
    return (
        observation.owned is False
        and observation.alive is False
        and observation.observed is None
        and observation.refusal_reason == "process-dead"
    )


__all__ = ["OwnedTurnLiveness", "is_proven_owned_turn_dead"]
