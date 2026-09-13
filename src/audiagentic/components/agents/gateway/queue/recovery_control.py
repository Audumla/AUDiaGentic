"""Private control signals for non-terminal gateway recovery."""

from __future__ import annotations

from audiagentic.foundation.contracts.errors import AudiaGenticError


class RecoveryDeferred(Exception):
    """The request remains running and must be retried by the queue.

    This is deliberately separate from :class:`AudiaGenticError`: a provider
    reattach failure is not a request failure when the previous generation may
    already have submitted the turn.
    """

    def __init__(
        self,
        error: AudiaGenticError,
        *,
        phase: str = "rehydrate-retry",
        side_effect_state: str = "may-have-started",
    ) -> None:
        self.error = error
        self.phase = phase
        self.side_effect_state = side_effect_state
        super().__init__(error.message)
