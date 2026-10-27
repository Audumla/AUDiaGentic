"""Bounded node error projection for existing gateway recovery diagnostics.

No telemetry storage, retry policy, lifecycle or I/O is owned here. Raw messages,
exception types and arbitrary details never enter the projected error.
"""
from __future__ import annotations

from collections.abc import Mapping

from audiagentic.components.agents.gateway.diagnostics import ObservationPhase
from audiagentic.foundation.contracts.errors import AudiaGenticError, get_error_resolution

# Small owner-local diagnostic projection, consumed by existing recovery error
# persistence/diagnostics. Neither raw exceptions nor remote reason strings are
# durable facts. These stages are not another lifecycle or retry authority.
_STAGE_FACTS = {
    "ownership": (ObservationPhase.OWNERSHIP, "owner-fence-changed"),
    "admission": (ObservationPhase.ADMISSION, "admission-snapshot-invalid"),
    "transport": (ObservationPhase.PRE_SUBMIT, "grant-or-connection-changed"),
    "prepare": (ObservationPhase.PRE_SUBMIT, "preparation-failed"),
    "prepared-reply": (ObservationPhase.PRE_SUBMIT, "preparation-mismatch"),
    "retain-prepared": (ObservationPhase.PRE_SUBMIT, "prepared-evidence-unavailable"),
    "bind": (ObservationPhase.SUBMIT_INTENT, "grant-or-connection-changed"),
    "command": (ObservationPhase.SUBMIT_INTENT, "command-delivery-uncertain"),
    "observe": (ObservationPhase.RECONCILIATION, "node-reconciliation-required"),
    "receipt": (ObservationPhase.RECONCILIATION, "receipt-custody-unavailable"),
    "artifact": (ObservationPhase.RECONCILIATION, "artifact-transfer-unavailable"),
    "publication": (ObservationPhase.FINALIZATION, "artifact-publication-unavailable"),
}
_REASONS = frozenset(reason for _, reason in _STAGE_FACTS.values()) | {
    "transport-unavailable", "preparation-rejected", "preparation-timeout", "transport-timeout",
    "connection-replaced-or-closed", "capacity-occupied",
    "attempt-not-dispatchable", "internal-failure",
    "receipt-channel-replaced", "receipt-target-mismatch",
    "receipt-cursor-unreadable", "receipt-custody-uncertain", "receipt-log-changed",
    "receipt-cursor-mismatch", "receipt-stream-gap",
    "artifact-channel-replaced", "artifact-transfer-mismatch", "artifact-kind-unsupported",
    "artifact-read-budget-exhausted", "artifact-receipt-pending",
}


def _registered_code(code):
    # These three node public codes are already registered component contracts
    # (also used by NodeConnection before component-registry bootstrap). Other
    # owners' codes must be present in the existing loaded resolution registry.
    return isinstance(code, str) and (code in {"VAL-AGND-001", "CON-AGND-001", "IO-AGND-001"}
                                      or get_error_resolution(code) is not None)


def sanitize_node_error(error, stage=None, reason=None, phase=None) -> AudiaGenticError:
    """Retain only registered code and allowlisted stage/reason/phase facts.

    With stage=None (the default), a validated source stage survives queue
    projection; missing/invalid stages fall back to observe. Explicit stages
    are validated independently. Phase must be an existing ObservationPhase.
    Error mappings are accepted for code-only wire projections; their messages
    and all non-allowlisted details are discarded just like exception content.
    """
    source_code = error.code if isinstance(error, AudiaGenticError) else (
        error.get("code") if isinstance(error, Mapping) else None)
    registered = _registered_code(source_code)
    source_details = error.details if isinstance(error, AudiaGenticError) else (
        error.get("details") if isinstance(error, Mapping) else None)
    details = source_details if registered and isinstance(source_details, Mapping) else {}
    if stage is None:
        stage = details.get("stage")
    stage = stage if isinstance(stage, str) and stage in _STAGE_FACTS else "observe"
    default_phase, default_reason = _STAGE_FACTS[stage]
    selected_phase = phase if phase is not None else details.get("phase")
    try:
        phase = ObservationPhase(selected_phase) if selected_phase is not None else default_phase
    except (ValueError, TypeError):
        phase = default_phase
    code = source_code if registered else ("CON-AGND-001" if error is None else "IO-AGND-001")
    retained_reason = details.get("reason-code") or details.get("reason_code")
    if not isinstance(reason, str) or reason not in _REASONS:
        reason = retained_reason if isinstance(retained_reason, str) and retained_reason in _REASONS else default_reason
    if isinstance(error, TimeoutError):
        reason = "preparation-timeout" if stage == "prepare" else "transport-timeout"
    return AudiaGenticError(code=code, kind="agents-node", message="Node work deferred at a validated control boundary",
        details={"reason-code": reason, "stage": stage, "phase": phase.value})


__all__ = ["sanitize_node_error"]
