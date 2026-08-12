"""Harness status observer capability descriptor (AS19 stage-2).

Declares the capabilities an observer adapter can provide — mechanism,
supported status strings, and lifecycle installation mode. Foundation-safe:
imports only from audiagentic.foundation (no agents or providers internals).
No provider-native event names; no raw payloads.

This module lives in ``providers/contracts`` because the capability descriptor
is part of the provider-side contract surface — adapters declare what they
can do, and the harness queries this declaration before resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.transports.agent_session import (
    TransportObservation,
    TransportObservationKind,
)
from audiagentic.foundation.transports.harness_status_observer import (
    StatusEvidence,
    StatusEvidenceSemanticStrength,
    StatusEvidenceSourceKind,
    StatusObserverLease,
)

# ---------------------------------------------------------------------------
# Observer installation timing
# ---------------------------------------------------------------------------

ObserverInstallationTiming = Literal["session-open", "first-turn", "lazy"]
"""When the observer is installed relative to session/turn lifecycle.

Distinct from foundation.transports.session_surface.LifecycleInstallation,
which describes installation *mechanism* (managed-hook/managed-plugin/...),
not *timing*.
"""

# ---------------------------------------------------------------------------
# Capability descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HarnessStatusObserverCapability:
    """Declares observer capabilities for a single mechanism.

    ``mechanism`` is a closed StrEnum from the foundation transport layer.
    ``supported_statuses`` is a frozenset of canonical status strings only
    (no provider-native event names). ``lifecycle_installation`` indicates
    whether the observer is installed at session open, on first turn, or
    lazily.

    This type carries no raw payloads and no provider-specific identifiers;
    it is a pure declaration consumed by the harness resolver.
    """

    mechanism: StatusEvidenceSourceKind
    supported_statuses: frozenset[str]
    lifecycle_installation: ObserverInstallationTiming = "session-open"

    def __post_init__(self) -> None:
        if not isinstance(self.mechanism, StatusEvidenceSourceKind):
            raise make_error(
                prefix="VAL", component="PROV-OBS", number=1,
                kind="harness-status-observer-capability",
                message="mechanism must be a StatusEvidenceSourceKind value",
                details={"mechanism": repr(self.mechanism)},
            )
        if not isinstance(self.supported_statuses, frozenset):
            raise make_error(
                prefix="VAL", component="PROV-OBS", number=2,
                kind="harness-status-observer-capability",
                message="supported_statuses must be a frozenset of strings",
                details={"type": type(self.supported_statuses).__name__},
            )
        for status in self.supported_statuses:
            if not isinstance(status, str) or not status:
                raise make_error(
                    prefix="VAL", component="PROV-OBS", number=3,
                    kind="harness-status-observer-capability",
                    message="each supported_status must be a non-empty string",
                    details={"status": repr(status)},
                )
        if self.lifecycle_installation not in get_args(ObserverInstallationTiming):
            raise make_error(
                prefix="VAL", component="PROV-OBS", number=4,
                kind="harness-status-observer-capability",
                message="lifecycle_installation must be one of session-open/first-turn/lazy",
                details={"lifecycle_installation": repr(self.lifecycle_installation)},
            )

    def supports_status(self, status: str) -> bool:
        """Check if this capability covers a given status string."""
        return status in self.supported_statuses


# ---------------------------------------------------------------------------
# Canonical status mapping (TransportObservationKind → status string)
# ---------------------------------------------------------------------------

_KIND_TO_STATUS: dict[TransportObservationKind, str] = {
    TransportObservationKind.ACTIVITY: "model-thinking",
    TransportObservationKind.IN_PROGRESS: "in-progress",
    TransportObservationKind.TOOL_REQUESTED: "tool-calling",
    TransportObservationKind.PERMISSION_REQUESTED: "waiting-permission",
}

# Kinds that are projectable as status evidence (not all observations carry
# a meaningful status — terminal and errors are turn-state, not status).
_PROJECTABLE_KINDS = frozenset(_KIND_TO_STATUS.keys())


# ---------------------------------------------------------------------------
# Normalizer contract (AS19 stage-3)
# ---------------------------------------------------------------------------

def normalize_harness_status_observation(
    lease: StatusObserverLease,
    observation: TransportObservation,
) -> StatusEvidence | None:
    """Normalize a transport observation into canonical status evidence.

    Maps a :class:`TransportObservation` to :class:`StatusEvidence` using the
    canonical status mapping. Returns ``None`` when the observation kind is not
    projectable as status evidence (e.g. terminal, transport-error) — these are
    handled by the turn-state pipeline, not status observation.

    The resulting :class:`StatusEvidence` carries only bounded metadata:
    canonical status string, AG correlation IDs, source kind, and timestamp.
    No raw payload or provider-native event names leak through.

    Args:
        lease: The per-session observer binding (provides binding_id).
        observation: A transport observation from the session pipeline.

    Returns:
        A :class:`StatusEvidence` instance for projectable observations, or
        ``None`` when the observation kind is not a status-bearing kind.
    """
    kind = observation.kind
    if kind not in _PROJECTABLE_KINDS:
        return None

    # Derive canonical status string from the observation kind.
    status = _KIND_TO_STATUS[kind]

    # For ACTIVITY observations, refine the status based on model_activity.
    if kind == TransportObservationKind.ACTIVITY and observation.attributes:
        activity = observation.attributes.get("model_activity")
        if isinstance(activity, str) and activity:
            status = f"model-{activity}"

    # For TOOL_REQUESTED observations, refine based on tool_status.
    if kind == TransportObservationKind.TOOL_REQUESTED and observation.attributes:
        tool_status = observation.attributes.get("tool_status")
        if isinstance(tool_status, str) and tool_status == "pending":
            status = "tool-pending"

    # Build the StatusEvidence — all fields are bounded and redacted.
    # correlation_id is the observer binding_id: it links this evidence to
    # the specific observer lease that received the transport observation.
    return StatusEvidence(
        status=status,
        session_id=observation.ag_session_id,
        request_id=observation.turn_id,
        correlation_id=lease.binding_id,
        observed_at=observation.observed_at,
        sequence=observation.sequence,
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )
