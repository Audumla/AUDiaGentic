"""Bounded, provider-neutral diagnostics for gateway execution records.

Diagnostics are deliberately orthogonal to lifecycle state.  A request can be
``running`` while its provider side effect is ambiguous, or ``failed`` while
the provider itself was never reached.  This module supplies the small closed
vocabulary used by durable records, status projections, and operator tooling.
It never accepts raw prompts, DOM, CDP payloads, cookies, or tracebacks.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class FailureClass(StrEnum):
    PROVIDER_REJECTED = "provider-rejected"
    PROVIDER_ERROR = "provider-error"
    BROWSER_ADAPTER_ERROR = "browser-adapter-error"
    GATEWAY_OWNERSHIP_QUEUE_ERROR = "gateway-ownership-queue-error"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    STALE_PROGRESS = "stale-progress"
    AMBIGUOUS_SIDE_EFFECT = "ambiguous-side-effect"
    GATEWAY_RESTART = "gateway-restart"
    UNKNOWN = "unknown"


class ObservationPhase(StrEnum):
    ADMISSION = "admission"
    OWNERSHIP = "ownership"
    CAPACITY_WAIT = "capacity-wait"
    PRE_SUBMIT = "pre-submit"
    SUBMIT_INTENT = "submit-intent"
    SUBMISSION_PROOF = "submission-proof"
    IN_PROGRESS = "in-progress"
    TERMINAL_OBSERVATION = "terminal-observation"
    RECONCILIATION = "reconciliation"
    CANCELLATION = "cancellation"
    FINALIZATION = "finalization"


class SideEffectState(StrEnum):
    NOT_STARTED = "not-started"
    MAY_HAVE_STARTED = "may-have-started"
    SUBMISSION_PROVEN = "submission-proven"
    TERMINAL_EVIDENCE_SEEN = "terminal-evidence-seen"


class EvidenceCertainty(StrEnum):
    DEFINITIVE = "definitive"
    STRONG = "strong"
    WEAK = "weak"
    UNKNOWN = "unknown"


class RecoveryDisposition(StrEnum):
    RETRY_SAFE = "retry-safe"
    RECONCILE_REQUIRED = "reconcile-required"
    ADOPT_SAFE = "adopt-safe"
    OPERATOR_ADOPT_AVAILABLE = "operator-adopt-available"
    RETIRE_CONVERSATION_REQUIRED = "retire-conversation-required"
    BLOCKED = "blocked"
    NONE = "none"


_MAX_ID = 128
_MAX_TEXT = 512
_MAX_SIGNALS = 8
_MAX_EVIDENCE = 8
_SIDE_EFFECT_RANK = {
    SideEffectState.NOT_STARTED.value: 0,
    SideEffectState.MAY_HAVE_STARTED.value: 1,
    SideEffectState.SUBMISSION_PROVEN.value: 2,
    SideEffectState.TERMINAL_EVIDENCE_SEEN.value: 3,
}


def _text(value: Any, limit: int = _MAX_TEXT) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    value = value.replace("\x00", "")
    return value[:limit]


def _phase(value: Any, default: ObservationPhase) -> str:
    try:
        return ObservationPhase(str(value)).value
    except ValueError:
        return default.value


def _side_effect(value: Any, default: SideEffectState) -> str:
    try:
        return SideEffectState(str(value)).value
    except ValueError:
        return default.value


def _signals(details: Mapping[str, Any]) -> list[str]:
    raw = details.get("dom-signals") or details.get("provider-signals")
    if not isinstance(raw, (list, tuple)):
        return []
    return [s[:_MAX_ID] for s in raw if isinstance(s, str) and s][: _MAX_SIGNALS]


def classify_error(
    error: BaseException | Mapping[str, Any] | None,
    *,
    phase: str | None = None,
    side_effect_state: str | None = None,
) -> dict[str, Any]:
    """Return a bounded semantic diagnostics rollup for one failure/evidence.

    Provider error codes remain useful evidence, but are not themselves the
    semantic outcome.  In particular, submission uncertainty is never called a
    provider failure and a rate-limit dialog is only provider-rejected when it
    is attributable to this turn.
    """
    code = None
    details: Mapping[str, Any] = {}
    if isinstance(error, Mapping):
        code = error.get("code")
        raw_details = error.get("details")
        if isinstance(raw_details, Mapping):
            details = raw_details
    else:
        code = getattr(error, "code", None)
        raw_details = getattr(error, "details", None)
        if isinstance(raw_details, Mapping):
            details = raw_details
    code = _text(code, _MAX_ID)
    reason = _text(details.get("failure-reason") or details.get("reason-code"), _MAX_ID)
    if code == "CON-AGW-084" and reason is None:
        # Recovery emits this code when the owning gateway generation has
        # disappeared (normally a service restart). Keep the cause explicit
        # even though the recovery error has no provider detail payload.
        reason = "service-restart"
    attempted = bool(
        details.get("submission-attempted")
        or details.get("side-effect-attempted")
        or str(details.get("turn-state", "")) == "side-effect-attempted"
    )
    proven = bool(details.get("submission-proven"))
    ambiguous = bool(details.get("submission-ambiguous")) or attempted and not proven or str(details.get("turn-state", "")) in {
        "side-effect-attempted",
        "submission-ambiguous",
    }
    if code == "CON-AGW-084" and reason == "service-restart":
        classification = FailureClass.GATEWAY_RESTART
        certainty = EvidenceCertainty.DEFINITIVE
        recovery = RecoveryDisposition.RECONCILE_REQUIRED
        default_phase = ObservationPhase.RECONCILIATION
        default_side_effect = SideEffectState.MAY_HAVE_STARTED
    elif ambiguous or code == "EXT-GPTAUTO-004":
        classification = FailureClass.AMBIGUOUS_SIDE_EFFECT
        certainty = EvidenceCertainty.STRONG
        recovery = RecoveryDisposition.OPERATOR_ADOPT_AVAILABLE
        default_phase = ObservationPhase.RECONCILIATION
        default_side_effect = SideEffectState.MAY_HAVE_STARTED
    elif code == "EXT-GPTAUTO-002" and reason == "response-policy-timeout":
        classification = FailureClass.TIMEOUT
        certainty = EvidenceCertainty.STRONG
        recovery = RecoveryDisposition.RECONCILE_REQUIRED
        default_phase = ObservationPhase.TERMINAL_OBSERVATION
        default_side_effect = SideEffectState.MAY_HAVE_STARTED
    elif code == "EXT-GPTAUTO-002" and (
        reason in {"rate-limit-dialog", "rate-limit", "usage-limit"}
        or any(s in {"rate-limit-dialog", "rate-limit", "usage-limit"} for s in _signals(details))
    ):
        classification = FailureClass.PROVIDER_REJECTED
        certainty = EvidenceCertainty.STRONG
        recovery = RecoveryDisposition.RETRY_SAFE
        default_phase = ObservationPhase.TERMINAL_OBSERVATION
        default_side_effect = SideEffectState.NOT_STARTED
    elif code == "EXT-GPTAUTO-003":
        classification = FailureClass.BROWSER_ADAPTER_ERROR
        certainty = EvidenceCertainty.WEAK if not ambiguous else EvidenceCertainty.STRONG
        recovery = RecoveryDisposition.RECONCILE_REQUIRED if ambiguous else RecoveryDisposition.RETRY_SAFE
        default_phase = ObservationPhase.SUBMISSION_PROOF
        default_side_effect = SideEffectState.MAY_HAVE_STARTED if ambiguous else SideEffectState.NOT_STARTED
    elif code in {"TO-AGW-076", "TO-AGW-077"}:
        classification = FailureClass.TIMEOUT
        certainty = EvidenceCertainty.STRONG
        recovery = RecoveryDisposition.RECONCILE_REQUIRED
        default_phase = ObservationPhase.IN_PROGRESS
        default_side_effect = SideEffectState.MAY_HAVE_STARTED
    elif code in {"CON-AGW-071", "CON-AGW-083", "CON-AGW-101", "VAL-AGW-025"}:
        classification = FailureClass.GATEWAY_OWNERSHIP_QUEUE_ERROR
        certainty = EvidenceCertainty.DEFINITIVE
        recovery = RecoveryDisposition.RETRY_SAFE
        default_phase = ObservationPhase.OWNERSHIP
        default_side_effect = SideEffectState.NOT_STARTED
    elif code in {"CON-AGW-CANCELLED", "CANCELLED"}:
        classification = FailureClass.CANCELLED
        certainty = EvidenceCertainty.DEFINITIVE
        recovery = RecoveryDisposition.NONE
        default_phase = ObservationPhase.CANCELLATION
        default_side_effect = SideEffectState.MAY_HAVE_STARTED
    elif code and str(code).startswith("EXT-"):
        classification = FailureClass.PROVIDER_ERROR
        certainty = EvidenceCertainty.STRONG
        recovery = RecoveryDisposition.RECONCILE_REQUIRED
        default_phase = ObservationPhase.IN_PROGRESS
        default_side_effect = SideEffectState.MAY_HAVE_STARTED
    else:
        classification = FailureClass.UNKNOWN
        certainty = EvidenceCertainty.UNKNOWN
        recovery = RecoveryDisposition.BLOCKED
        default_phase = ObservationPhase.FINALIZATION
        default_side_effect = SideEffectState.NOT_STARTED
    result = {
        "version": 1,
        "classification": classification.value,
        "certainty": certainty.value,
        "phase": _phase(phase, default_phase),
        "side-effect-state": _side_effect(side_effect_state, default_side_effect),
        "resolution-state": "unresolved" if recovery not in {RecoveryDisposition.NONE, RecoveryDisposition.RETRY_SAFE} else "resolved",
        "failure-code": code,
        "reason-code": reason,
        "provider-signals": _signals(details),
        "evidence-count": 1,
        "coalesced-observation-count": 0,
        "recovery": {
            "disposition": recovery.value,
            "allowed-actions": _allowed_actions(recovery),
        },
    }
    # A provider-side attempt without proof is never safe to clear or retry,
    # regardless of which adapter error code wrapped the attempt.
    if attempted and not proven:
        result["classification"] = FailureClass.AMBIGUOUS_SIDE_EFFECT.value
        result["certainty"] = EvidenceCertainty.STRONG.value
        result["side-effect-state"] = SideEffectState.MAY_HAVE_STARTED.value
        result["resolution-state"] = "unresolved"
        result["recovery"] = {
            "disposition": RecoveryDisposition.RECONCILE_REQUIRED.value,
            "allowed-actions": ["reconcile", "abandon"],
        }
    return result


def stale_progress_diagnostic(
    *,
    phase: str = ObservationPhase.RECONCILIATION.value,
    side_effect_state: str = SideEffectState.MAY_HAVE_STARTED.value,
) -> dict[str, Any]:
    """Build non-terminal evidence for an expired activity observation.

    This is deliberately not produced by :func:`classify_error`: elapsed
    silence is an observation requiring reconciliation, not timeout proof.
    """
    return {
        "version": 1,
        "classification": FailureClass.STALE_PROGRESS.value,
        "certainty": EvidenceCertainty.WEAK.value,
        "phase": _phase(phase, ObservationPhase.RECONCILIATION),
        "side-effect-state": _side_effect(side_effect_state, SideEffectState.MAY_HAVE_STARTED),
        "resolution-state": "unresolved",
        "failure-code": None,
        "reason-code": "activity-lease-expired",
        "provider-signals": [],
        "evidence-count": 1,
        "coalesced-observation-count": 0,
        "recovery": {
            "disposition": RecoveryDisposition.RECONCILE_REQUIRED.value,
            "allowed-actions": _allowed_actions(RecoveryDisposition.RECONCILE_REQUIRED),
        },
    }


def merge_diagnostics(
    previous: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge a new rollup without regressing side-effect certainty."""
    merged = dict(candidate)
    if not isinstance(previous, Mapping):
        return merged
    previous_state = str(previous.get("side-effect-state", SideEffectState.NOT_STARTED.value))
    candidate_state = str(merged.get("side-effect-state", SideEffectState.NOT_STARTED.value))
    if _SIDE_EFFECT_RANK.get(previous_state, 0) > _SIDE_EFFECT_RANK.get(candidate_state, 0):
        merged["side-effect-state"] = previous_state
        merged["classification"] = previous.get("classification", merged.get("classification"))
        merged["certainty"] = previous.get("certainty", merged.get("certainty"))
        merged["resolution-state"] = "unresolved"
        merged["recovery"] = {
            "disposition": RecoveryDisposition.RECONCILE_REQUIRED.value,
            "allowed-actions": ["reconcile", "abandon"],
        }
    # An ambiguous observation remains unresolved while the side-effect axis
    # is unchanged or regresses. Once a later candidate carries stronger
    # proof (submission-proven or terminal-evidence-seen), allow its
    # resolution/classification to advance instead of pinning the record
    # forever in unresolved state.
    if (
        previous.get("classification") == FailureClass.AMBIGUOUS_SIDE_EFFECT.value
        and _SIDE_EFFECT_RANK.get(candidate_state, 0)
        <= _SIDE_EFFECT_RANK.get(previous_state, 0)
    ):
        merged["classification"] = previous["classification"]
        if merged.get("resolution-state") not in {"abandon-requested", "reconciliation-requested"}:
            merged["resolution-state"] = "unresolved"
    merged["evidence-count"] = max(int(previous.get("evidence-count", 0) or 0), int(merged.get("evidence-count", 0) or 0))
    merged["coalesced-observation-count"] = max(
        int(previous.get("coalesced-observation-count", 0) or 0),
        int(merged.get("coalesced-observation-count", 0) or 0),
    )
    return merged


def _allowed_actions(disposition: RecoveryDisposition) -> list[str]:
    return {
        # The public recovery endpoint deliberately has no force-resend or
        # generic retry operation.  A definitively unsubmitted request can be
        # cleared through the named safe operation instead.
        RecoveryDisposition.RETRY_SAFE: ["clear-not-submitted"],
        RecoveryDisposition.RECONCILE_REQUIRED: ["reconcile", "abandon"],
        RecoveryDisposition.ADOPT_SAFE: [],
        RecoveryDisposition.OPERATOR_ADOPT_AVAILABLE: ["reconcile", "abandon"],
        RecoveryDisposition.RETIRE_CONVERSATION_REQUIRED: ["abandon"],
        RecoveryDisposition.BLOCKED: [],
        RecoveryDisposition.NONE: [],
    }[disposition]


def evidence_from_activity(
    *,
    request_id: str,
    session_id: str | None,
    attempt_epoch: int,
    phase: str | None,
    source: str,
    source_sequence: int | None,
    activity_sequence: int,
    side_effect_state: str = SideEffectState.MAY_HAVE_STARTED.value,
) -> dict[str, Any]:
    """Create a bounded durable evidence item from accepted activity."""
    return {
        "evidence-id": f"ev_{activity_sequence}",
        "sequence": activity_sequence,
        "request-id": _text(request_id, _MAX_ID),
        "session-id": _text(session_id, _MAX_ID),
        "attempt-epoch": attempt_epoch,
        "phase": _phase(phase, ObservationPhase.IN_PROGRESS),
        "kind": "activity",
        "certainty": EvidenceCertainty.STRONG.value,
        "side-effect-state": _side_effect(side_effect_state, SideEffectState.MAY_HAVE_STARTED),
        "source": _text(source, _MAX_ID),
        "source-sequence": source_sequence,
    }


__all__ = [
    "EvidenceCertainty",
    "FailureClass",
    "ObservationPhase",
    "RecoveryDisposition",
    "SideEffectState",
    "classify_error",
    "stale_progress_diagnostic",
    "evidence_from_activity",
    "merge_diagnostics",
]
