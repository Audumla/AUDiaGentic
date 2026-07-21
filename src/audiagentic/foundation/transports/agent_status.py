"""AS37 — Agent status projection contract (Stage 1: foundation-neutral types).

Defines frozen, scalar-safe value types for the unified read-facing agent
status projection. Sits above AS19 (StatusEvidence), AS21 (lifecycle
decisions), AS28 (transport observations), and SH07 (durable request facts).

Stage-1 is pure value types only — no wiring, no durable state, no provider
imports. This contract is intentionally separate from:

- StatusEvidence (AS19) — lifecycle evidence with different retention rules
- SessionTurnResult (AS28) — carries bounded final_summary but not status
  projections
- ComponentOutputEvent — component logging/progress, not agent status
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from audiagentic.foundation.contracts.errors import make_error

# ---------------------------------------------------------------------------
# Coded error constants (registered in foundation/error-resolutions.yaml)
# ---------------------------------------------------------------------------

ERR_STATUS_TERMINAL_REQUIRES_OUTCOME: Final = "VAL-STATUS-001"
ERR_STATUS_NONTERMINAL_NO_OUTCOME: Final = "VAL-STATUS-002"
ERR_STATUS_INVALID_PROJECTED_AT: Final = "VAL-STATUS-003"

# ---------------------------------------------------------------------------
# Enums (closed sets)
# ---------------------------------------------------------------------------

class AgentStatusScope(StrEnum):
    """Scope at which the status projection is evaluated."""

    EXECUTION_REQUEST = "execution-request"
    SESSION = "session"
    TURN = "turn"
    WORKFLOW = "workflow"


class AgentLifecycle(StrEnum):
    """Agent lifecycle state for a single scope."""

    PENDING = "pending"
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETING = "completing"
    AVAILABLE = "available"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"


class AgentOutcome(StrEnum):
    """Terminal outcome reason. Set only when lifecycle == terminal."""

    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    REJECTED = "rejected"
    TIMED_OUT = "timed-out"
    EXPIRED = "expired"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"


class AgentWaitReason(StrEnum):
    """Reason an agent is in the waiting state.

    May be None when evidence does not determine why the agent is waiting.
    """

    PERMISSION = "permission"
    QUEUE_CAPACITY = "queue-capacity"
    RETRY_BACKOFF = "retry-backoff"
    DEPENDENCY = "dependency"
    CHILD_WORK = "child-work"
    PROVIDER_RESPONSE = "provider-response"
    TOOL_RESPONSE = "tool-response"
    OPERATOR_ACTION = "operator-action"
    RECOVERY_DECISION = "recovery-decision"
    UNKNOWN = "unknown"


class StatusEvidenceConfidence(StrEnum):
    """Confidence level of the evidence backing a decision."""

    VALIDATED = "validated"
    CANDIDATE = "candidate"
    CONTRADICTORY = "contradictory"
    INSUFFICIENT = "insufficient"
    REJECTED = "rejected"

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentStatusDecisions:
    """AS21-produced lifecycle decision flags.

    Encapsulates the read-facing slice of AS21 decisions used to inform
    status projections. All fields are required — callers must supply
    explicit values rather than relying on defaults.
    """

    accepts_new_turn: bool
    session_reusable: bool
    turn_terminal: bool
    dependent_work_releasable: bool
    evidence_confidence: StatusEvidenceConfidence
    reason: str


@dataclass(frozen=True)
class AgentStatusSnapshot:
    """Immutable projection snapshot for one scope.

    Represents a point-in-time read of agent status at a specific scope
    (execution-request, session, turn, or workflow). Carries the lifecycle
    state, optional outcome (terminal only), optional wait reason (waiting
    only), and AS21 decision flags.

    Validation rules:
    - Terminal lifecycle requires non-None outcome.
    - Non-terminal lifecycle requires outcome to be None.
    - Waiting lifecycle may or may not have a wait_reason (evidence may
      not know why the agent is waiting).
    - ``projected_at`` must be a non-empty string (ISO-8601 expected).
    """

    scope: AgentStatusScope
    lifecycle: AgentLifecycle
    projected_at: str
    outcome: AgentOutcome | None = None  # None when lifecycle != terminal
    wait_reason: AgentWaitReason | None = None  # Only when lifecycle == waiting
    decisions: AgentStatusDecisions | None = None
    request_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    generation: int | None = None
    attempt: int | None = None
    observed_at: str | None = None

    def __post_init__(self) -> None:
        # --- scope validation ---
        if not isinstance(self.scope, AgentStatusScope):
            raise make_error(
                prefix="VAL", component="STATUS", number=1,
                kind="agent-status-validation",
                message=f"scope must be an AgentStatusScope value, "
                        f"got {self.scope!r}",
                details={"value": self.scope},
            )

        # --- projected_at validation ---
        if not isinstance(self.projected_at, str) or not self.projected_at:
            raise make_error(
                prefix="VAL", component="STATUS", number=3,
                kind="agent-status-validation",
                message="projected_at must be a non-empty string (ISO-8601)",
            )

        # --- lifecycle / outcome invariants ---
        if self.lifecycle == AgentLifecycle.TERMINAL and self.outcome is None:
            raise make_error(
                prefix="VAL", component="STATUS", number=1,
                kind="agent-status-validation",
                message="terminal lifecycle requires a non-None outcome",
                details={"lifecycle": self.lifecycle.value},
            )

        if self.lifecycle != AgentLifecycle.TERMINAL and self.outcome is not None:
            raise make_error(
                prefix="VAL", component="STATUS", number=2,
                kind="agent-status-validation",
                message=f"outcome must be None for non-terminal lifecycle "
                        f"{self.lifecycle.value}",
                details={"lifecycle": self.lifecycle.value, "outcome": str(self.outcome)},
            )
