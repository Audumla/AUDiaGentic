"""Pure session-lifecycle projector (plan agent-sessions AS21).

Accepts validated correlated terminal/activity evidence as an iterable of
``SessionLifecycleEvidence`` and projects a coarse session state with explicit
decision flags.  No durable storage, no provider imports, no gateway runtime,
MCP, or event bus dependency -- importable in isolation.

SH07 gateway request records and agent-jobs workflow job records remain distinct
authorities that consume the projection exactly once under their own authority.
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass
from threading import Lock
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

# ---------------------------------------------------------------------------
# Ephemeral keyed projection registry (AS21 consumer slice)
#
# Receives only accepted AS19 StatusEvidence, maps known statuses to EvidenceKind,
# feeds the pure projector, and retains the latest decision for status read
# projection. No terminal inference: observer data never produces terminal-success,
# terminal-failed, etc.
# ---------------------------------------------------------------------------

# Mapping from AS19 StatusEvidence.status strings → EvidenceKind.
# Only non-terminal statuses are mapped; terminal events come from the turn-state
# pipeline (TransportObservationKind.TERMINAL), not from status observation.
_STATUS_TO_EVIDENCE_KIND: dict[str, EvidenceKind] = {
    "model-thinking": "activity",
    "model-generating": "activity",
    "tool-calling": "tool-active",
    "tool-pending": "tool-active",
    "waiting-permission": "permission-wait",
    "tool-completed": "tool-completed",
}


def _map_status_to_evidence_kind(status: str) -> EvidenceKind | None:
    """Map a StatusEvidence.status string to an AS21 EvidenceKind.

    Returns None for unknown or terminal statuses — observer data never
    produces terminal-success, terminal-failed, etc. (no terminal inference).
    """
    return _STATUS_TO_EVIDENCE_KIND.get(status)


@dataclass(frozen=True)
class _EvidenceEntry:
    """Internal: one accepted evidence item with allocated sequence."""
    kind: EvidenceKind
    sequence: int
    source: str


class SessionEvidenceProjection:
    """Ephemeral keyed projection registry (AS21 consumer slice).

    Keyed by (session_id, request_id). Accepts only accepted AS19 scalar
    StatusEvidence, maps known statuses to EvidenceKind, feeds the pure
    projector, and retains the latest decision for status read projection.

    Thread-safe: uses a Lock for registry mutations. No durable storage —
    in-memory only, lifetime bounded by the session handle.

    No terminal inference: observer data never produces terminal-success,
    terminal-failed, etc. Only non-terminal status-bearing observations are
    mapped.

    No SH07/agent-jobs mutation: this class reads and projects only; it
    never mutates request or job state.
    """

    def __init__(self) -> None:
        # (session_id, request_id) → list of SessionLifecycleEvidence
        self._registry: MutableMapping[
            tuple[str, str], list[SessionLifecycleEvidence]
        ] = {}
        # (session_id, request_id) → latest projected decision
        self._decisions: MutableMapping[
            tuple[str, str], SessionLifecycleDecision
        ] = {}
        # (session_id, request_id) → next sequence counter
        self._sequence_counters: MutableMapping[
            tuple[str, str], int
        ] = {}
        self._lock = Lock()

    def accept(self, evidence: object) -> bool:
        """Accept a normalized AS19 StatusEvidence and update the projection.

        Validates the evidence is accepted (non-None, known status, non-terminal).
        Maps to EvidenceKind, preserves source sequence or allocates strict local
        sequence, feeds project_session_lifecycle(), and retains latest decision.

        Args:
            evidence: A StatusEvidence instance from the AS19 observer lease.

        Returns:
            True if evidence was accepted and projected; False if rejected
            (unknown status, terminal status, or invalid).
        """
        # Import lazily to avoid circular deps at module level
        from audiagentic.foundation.transports.harness_status_observer import (
            StatusEvidence,
        )

        if not isinstance(evidence, StatusEvidence):
            return False

        if not evidence.session_id:
            return False

        # No request_id → session-level only; use a sentinel.
        request_key = evidence.request_id or "__session__"

        # Map status → EvidenceKind; reject unknown/terminal statuses.
        kind = _map_status_to_evidence_kind(evidence.status)
        if kind is None:
            return False  # unknown status or terminal — no inference

        key = (evidence.session_id, request_key)

        with self._lock:
            # Allocate or preserve sequence.
            if evidence.sequence is not None and evidence.sequence > 0:
                seq = evidence.sequence
            else:
                seq = self._sequence_counters.get(key, 0) + 1
                self._sequence_counters[key] = seq

            lifecycle_ev = SessionLifecycleEvidence(
                session_id=evidence.session_id,
                turn_id=request_key,
                sequence=seq,
                kind=kind,
                correlation_id=evidence.correlation_id,
                timestamp=evidence.observed_at,
                validation_state="validated",
                source="status-observer",
            )

            # Append to registry.
            if key not in self._registry:
                self._registry[key] = []
            self._registry[key].append(lifecycle_ev)

            # Project through the pure projector.
            decision = project_session_lifecycle(self._registry[key])
            self._decisions[key] = decision

        return True

    def latest_decision(
        self,
        session_id: str,
        request_id: str | None = None,
    ) -> SessionLifecycleDecision | None:
        """Return the latest projected decision for a session/request key.

        Args:
            session_id: The AG session ID.
            request_id: The request/turn ID (optional; None → session-level).

        Returns:
            The latest SessionLifecycleDecision, or None if no evidence
            has been accepted for this key.
        """
        request_key = request_id or "__session__"
        with self._lock:
            return self._decisions.get((session_id, request_key))

    def latest_decision_for_key(
        self,
        session_id: str,
        request_id: str,
    ) -> SessionLifecycleDecision | None:
        """Return the latest projected decision for a specific (session, request) key.

        Unlike ``latest_decision``, this requires an explicit request_id
        and does not fall back to a sentinel.
        """
        with self._lock:
            return self._decisions.get((session_id, request_id))

    def redacted_status_snapshot(
        self,
        session_id: str,
        request_id: str | None = None,
    ) -> dict:
        """Expose a redacted lifecycle-decision status snapshot.

        Returns only scalar decision fields — no raw evidence, no content,
        no provider refs. Used by session_runtime_status() for live diagnostics.
        """
        decision = self.latest_decision(session_id, request_id)
        if decision is None:
            return {
                "lifecycle-decision": None,
                "coarse-state": "unknown",
                "evidence-accepted": False,
            }
        return {
            "lifecycle-decision": {
                "coarse-state": decision.coarse_state,
                "accepts-new-turn": decision.accepts_new_turn,
                "session-reusable": decision.session_reusable,
                "turn-terminal": decision.turn_terminal,
                "dependent-work-releasable": decision.dependent_work_releasable,
                "evidence-state": decision.evidence_state,
                "reason": decision.reason,
            },
            "coarse-state": decision.coarse_state,
            "evidence-accepted": True,
        }

    def _get_evidence_list(
        self,
        session_id: str,
        request_id: str | None = None,
    ) -> list[SessionLifecycleEvidence]:
        """Internal: get the evidence list for a key (read-only access).

        Returns a copy of the list to prevent external mutation.
        """
        request_key = request_id or "__session__"
        with self._lock:
            return list(self._registry.get((session_id, request_key), []))

    def clear_for_session(self, session_id: str) -> None:
        """Clear all entries for a specific session (e.g. on session close)."""
        with self._lock:
            keys_to_remove = [
                k for k in self._registry if k[0] == session_id
            ]
            for key in keys_to_remove:
                self._registry.pop(key, None)
                self._decisions.pop(key, None)
                self._sequence_counters.pop(key, None)

    def clear(self) -> None:
        """Clear all registry state (e.g. on runtime shutdown)."""
        with self._lock:
            self._registry.clear()
            self._decisions.clear()
            self._sequence_counters.clear()


# ---------------------------------------------------------------------------
# AS21 → AS37 adapter: SessionLifecycleDecision → AgentStatusSnapshot
# ---------------------------------------------------------------------------

_EVIDENCE_STATE_TO_CONFIDENCE: dict[str, str] = {
    "accepted": "validated",
    "candidate-only": "candidate",
    "contradictory": "contradictory",
    "insufficient": "insufficient",
    "rejected": "rejected",
}

_COARSE_TO_LIFECYCLE: dict[str, str] = {
    "active": "active",
    "waiting": "waiting",
    "completing": "completing",
    "available": "available",
    "failed": "terminal",
    "unknown": "unknown",
}


def snapshot_from_decision(
    decision: SessionLifecycleDecision,
    *,
    scope: str = "execution-request",
    request_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    generation: int | None = None,
    attempt: int | None = None,
    observed_at: str | None = None,
) -> object:
    """Map an AS21 SessionLifecycleDecision to an AS37 AgentStatusSnapshot.

    ``scope`` accepts an ``AgentStatusScope`` member or its string value
    (e.g. ``"execution-request"``).  AS37 types are imported lazily so the
    module remains importable in isolation.
    """
    from audiagentic.foundation.transports.agent_status import (
        AgentLifecycle,
        AgentOutcome,
        AgentStatusDecisions,
        AgentStatusScope,
        AgentStatusSnapshot,
        StatusEvidenceConfidence,
    )

    # Normalise scope to the enum instance.
    if isinstance(scope, str):
        scope = AgentStatusScope(scope)

    lifecycle_value = _COARSE_TO_LIFECYCLE[decision.coarse_state]

    # Determine outcome: only set for terminal lifecycle.
    outcome: AgentOutcome | None = None
    if decision.coarse_state == "failed":
        outcome = AgentOutcome.FAILED

    confidence_key = _EVIDENCE_STATE_TO_CONFIDENCE.get(
        decision.evidence_state, "insufficient"
    )
    evidence_confidence = StatusEvidenceConfidence(confidence_key)

    projected_at = observed_at or datetime.datetime.now(
        tz=datetime.timezone.utc
    ).isoformat()

    lifecycle = AgentLifecycle(lifecycle_value)

    decisions = AgentStatusDecisions(
        accepts_new_turn=decision.accepts_new_turn,
        session_reusable=decision.session_reusable,
        turn_terminal=decision.turn_terminal,
        dependent_work_releasable=decision.dependent_work_releasable,
        evidence_confidence=evidence_confidence,
        reason=decision.reason,
    )

    return AgentStatusSnapshot(
        scope=scope,
        lifecycle=lifecycle,
        projected_at=projected_at,
        outcome=outcome,
        decisions=decisions,
        request_id=request_id,
        session_id=session_id,
        turn_id=turn_id,
        generation=generation,
        attempt=attempt,
        observed_at=observed_at,
    )
