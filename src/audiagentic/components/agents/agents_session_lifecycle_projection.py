"""Pure session-lifecycle projector (plan agent-sessions AS21).

Accepts validated correlated terminal/activity evidence as an iterable of
``SessionLifecycleEvidence`` and projects a coarse session state with explicit
decision flags.  No durable storage, no provider imports, no gateway runtime,
MCP, or event bus dependency -- importable in isolation.

SH07 gateway request records and agent-jobs workflow job records remain distinct
authorities that consume the projection exactly once under their own authority.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------

EvidenceKind = Literal[
    "turn-started",
    "activity",
    "waiting",
    "tool-active",
    "tool-completed",
    "permission-wait",
    "terminal-success",
    "terminal-cancelled",
    "terminal-failed",
    "transport-closed",
    "transport-error",
    "finalization-committed",
    "finalization-failed",
    "blocking-work-cleared",
]

CoarseSessionState = Literal[
    "active",
    "waiting",
    "completing",
    "available",
    "failed",
    "unknown",
]

_ValidationState = Literal["validated", "candidate", "rejected"]

_EvidenceState = Literal[
    "accepted",
    "candidate-only",
    "contradictory",
    "insufficient",
    "rejected",
]

_ACTIVE_KINDS: frozenset[EvidenceKind] = frozenset({
    "turn-started",
    "activity",
    "tool-active",
})

_WAITING_KINDS: frozenset[EvidenceKind] = frozenset({
    "waiting",
    "permission-wait",
})

_TERMINAL_KINDS: frozenset[EvidenceKind] = frozenset({
    "terminal-success",
    "terminal-cancelled",
    "terminal-failed",
})

_FAILURE_KINDS: frozenset[EvidenceKind] = frozenset({
    "terminal-failed",
    "transport-closed",
    "transport-error",
    "finalization-failed",
})

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionLifecycleEvidence:
    """Normalized, redacted lifecycle evidence for one session turn event.

    No raw prompts, output text, tool arguments, protocol payloads, provider
    binding internals, or secrets.  Only bounded safe scalar values survive.
    """
    session_id: str
    turn_id: str
    sequence: int
    kind: EvidenceKind
    correlation_id: str | None = None
    timestamp: str | None = None
    validation_state: _ValidationState = "validated"
    source: str = "transport"


@dataclass(frozen=True)
class SessionLifecycleDecision:
    """Projected coarse session state and decision flags.

    Scheduler code consumes these explicit flags; it does not infer policy
    from state labels alone.  ``unknown`` is always conservative.
    """
    coarse_state: CoarseSessionState
    accepts_new_turn: bool
    session_reusable: bool
    turn_terminal: bool
    dependent_work_releasable: bool
    evidence_state: _EvidenceState
    reason: str

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _conservative_unknown(reason: str) -> SessionLifecycleDecision:
    return SessionLifecycleDecision(
        coarse_state="unknown",
        accepts_new_turn=False,
        session_reusable=False,
        turn_terminal=False,
        dependent_work_releasable=False,
        evidence_state="insufficient",
        reason=reason,
    )

# ---------------------------------------------------------------------------
# Main projector
# ---------------------------------------------------------------------------


def project_session_lifecycle(
    evidence: Iterable[SessionLifecycleEvidence],
) -> SessionLifecycleDecision:
    """Project coarse session state and decision flags from correlated evidence.

    Rules (from AS21 plan):
        1. Empty, rejected-only, candidate-only, missing turn correlation,
           duplicate/lower sequence contradiction, or mixed turn IDs returns
           conservative ``unknown`` with every release/reuse flag false.
        2. ``turn-started``, ``activity``, and ``tool-active`` project ``active``;
           ``waiting`` and ``permission-wait`` project ``waiting``; terminal
           evidence without finalization projects ``completing``.
        3. ``terminal-success`` + ``finalization-committed`` +
           ``blocking-work-cleared`` is the only path to ``available`` with all
           flags true.
        4. ``terminal-cancelled`` + ``finalization-committed`` may set
           ``turn_terminal=True`` and ``dependent_work_releasable=True``, but
           ``session_reusable`` is true only if no failure/close evidence exists
           and ``blocking-work-cleared`` is present.
        5. ``terminal-failed``, ``transport-error``, ``transport-closed``, or
           ``finalization-failed`` projects ``failed`` unless contradicted, with
           reuse false. ``dependent_work_releasable`` is true only after
           finalization has committed or failed under the owning request authority.
        6. A terminal protocol event alone never means ``available``;
           commit-before-available is mandatory.
    """
    items = list(evidence)

    # -- Guard: empty input --------------------------------------------------
    if not items:
        return _conservative_unknown("no evidence provided")

    # -- Guard: all rejected -------------------------------------------------
    if all(e.validation_state == "rejected" for e in items):
        return SessionLifecycleDecision(
            coarse_state="unknown",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="rejected",
            reason="all evidence rejected",
        )

    # -- Guard: candidate-only (no validated evidence) -----------------------
    if all(e.validation_state != "validated" for e in items):
        return SessionLifecycleDecision(
            coarse_state="unknown",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="candidate-only",
            reason="no validated evidence; candidate only",
        )

    # -- Guard: mixed turn IDs (missing turn correlation) --------------------
    turn_ids = {e.turn_id for e in items}
    if len(turn_ids) > 1:
        return _conservative_unknown(
            f"mixed turn IDs across evidence ({len(turn_ids)} turns)",
        )

    # -- Guard: contradictory sequence (lower sequence after higher one) -----
    # A lower-sequence event appearing after a higher one means the evidence
    # was observed out of order, which is contradictory.  Increasing sequences
    # in the iterable are normal progression and NOT contradictory.
    validated = [e for e in items if e.validation_state == "validated"]
    has_sequence_contradiction = False
    seen_max = -1
    for e in validated:
        if e.sequence < seen_max:
            has_sequence_contradiction = True
            break
        seen_max = max(seen_max, e.sequence)
    if has_sequence_contradiction:
        return SessionLifecycleDecision(
            coarse_state="unknown",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="contradictory",
            reason="duplicate or lower sequence contradiction",
        )

    # -- Filter to validated evidence for projection -------------------------
    kinds = {e.kind for e in validated}

    # -- Aggregate presence flags --------------------------------------------
    has_terminal_success = "terminal-success" in kinds
    has_terminal_cancelled = "terminal-cancelled" in kinds
    has_terminal_failed = "terminal-failed" in kinds
    has_transport_closed = "transport-closed" in kinds
    has_transport_error = "transport-error" in kinds
    has_finalization_committed = "finalization-committed" in kinds
    has_finalization_failed = "finalization-failed" in kinds
    has_blocking_work_cleared = "blocking-work-cleared" in kinds
    has_active = bool(kinds & _ACTIVE_KINDS)
    has_waiting = bool(kinds & _WAITING_KINDS)

    has_any_failure = (
        has_terminal_failed
        or has_transport_closed
        or has_transport_error
        or has_finalization_failed
    )

    # -- Rule: terminal-success + finalization-committed + blocking-work-cleared
    #     is the ONLY path to available ---------------------------------------
    if (
        has_terminal_success
        and has_finalization_committed
        and has_blocking_work_cleared
        and not has_any_failure
        and not has_terminal_cancelled
        and not has_active
        and not has_waiting
    ):
        return SessionLifecycleDecision(
            coarse_state="available",
            accepts_new_turn=True,
            session_reusable=True,
            turn_terminal=True,
            dependent_work_releasable=True,
            evidence_state="accepted",
            reason="terminal-success + finalization-committed + blocking-work-cleared",
        )

    # -- Rule: terminal-cancelled + finalization-committed -------------------
    if has_terminal_cancelled and has_finalization_committed:
        session_reusable = (
            not has_any_failure
            and has_blocking_work_cleared
            and not has_active
            and not has_waiting
        )
        return SessionLifecycleDecision(
            coarse_state="available" if session_reusable else "completing",
            accepts_new_turn=session_reusable,
            session_reusable=session_reusable,
            turn_terminal=True,
            dependent_work_releasable=True,
            evidence_state="accepted",
            reason=(
                "terminal-cancelled + finalization-committed"
                + (
                    "; reusable"
                    if session_reusable
                    else "; not reusable: failure or blocking work"
                )
            ),
        )

    # -- Rule: failure kinds project failed ----------------------------------
    if has_any_failure:
        work_releasable = has_finalization_committed or has_finalization_failed
        return SessionLifecycleDecision(
            coarse_state="failed",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=has_terminal_failed,
            dependent_work_releasable=work_releasable,
            evidence_state="accepted",
            reason="failure evidence: "
            + ", ".join(sorted({k for k in kinds if k in _FAILURE_KINDS})),
        )

    # -- Rule: terminal without finalization -> completing -------------------
    has_terminal = bool(kinds & _TERMINAL_KINDS)
    if has_terminal and not has_finalization_committed:
        return SessionLifecycleDecision(
            coarse_state="completing",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=has_terminal_success or has_terminal_cancelled,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="terminal without finalization committed",
        )

    # -- Rule: waiting -------------------------------------------------------
    if has_waiting and not has_active and not has_terminal:
        return SessionLifecycleDecision(
            coarse_state="waiting",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="waiting or permission-wait evidence",
        )

    # -- Rule: active --------------------------------------------------------
    if has_active and not has_waiting and not has_terminal:
        return SessionLifecycleDecision(
            coarse_state="active",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="active work evidence",
        )

    # -- Rule: mixed active + waiting (waiting takes precedence) -------------
    if has_active and has_waiting:
        return SessionLifecycleDecision(
            coarse_state="waiting",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="active + waiting evidence; waiting takes precedence",
        )

    # -- Default: insufficient / unknown -------------------------------------
    return _conservative_unknown("insufficient validated evidence for a decision")

# ---------------------------------------------------------------------------
# Adapter from existing redacted session-turn projection
# ---------------------------------------------------------------------------

_REDACTED_KEYS = frozenset({
    "native-topic",
    "prompt-body",
    "output",
    "tool-args",
    "provider-session-ref",
    "provider-ref-key",
    "binding",
})

# Mapping from timeline event names to EvidenceKind.
_EVENT_KIND_MAP: dict[str, EvidenceKind] = {
    "session.turn.started": "turn-started",
    "session.turn.finished": "terminal-success",
    "session.turn.recorded": "finalization-committed",
}


def evidence_from_latest_turn_projection(
    projection: dict,
    *,
    default_validation_state: _ValidationState = "validated",
) -> SessionLifecycleEvidence | None:
    """Adapter: convert a redacted session-turn projection to lifecycle evidence.

    Rejects/ignores content-bearing fields (prompt, output, tool args,
    native-topic, provider refs).  Returns None if the projection is empty or
    contains only rejected keys.
    """
    if not projection or not isinstance(projection, dict):
        return None

    for key in projection:
        if key.lower().replace("_", "-") in _REDACTED_KEYS:
            return None

    event = projection.get("event")
    if not isinstance(event, str):
        return None

    session_id = projection.get("session-id")
    if not isinstance(session_id, str):
        return None

    request_id = projection.get("request-id")
    if not isinstance(request_id, str):
        return None

    kind = _EVENT_KIND_MAP.get(event)
    if kind is None:
        if event.startswith("session.turn."):
            return SessionLifecycleEvidence(
                session_id=session_id,
                turn_id=request_id,
                sequence=int(projection.get("sequence") or 0),
                kind="activity",
                correlation_id=projection.get("correlation-id"),
                timestamp=projection.get("timestamp"),
                validation_state=default_validation_state,
                source="timeline",
            )
        return None

    return SessionLifecycleEvidence(
        session_id=session_id,
        turn_id=request_id,
        sequence=int(projection.get("sequence") or 0),
        kind=kind,
        correlation_id=projection.get("correlation-id"),
        timestamp=projection.get("timestamp"),
        validation_state=default_validation_state,
        source="timeline",
    )
