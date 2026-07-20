"""Foundation-neutral harness status observer contract (AS19 stage-1).

Defines frozen, scalar-safe value types for status observation and observer
leasing. No components.agents or components.providers imports. Status evidence
carries only bounded canonical metadata; raw payload and provider-specific
event names are redacted at the adapter boundary.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from audiagentic.foundation.contracts.errors import make_error

# ---------------------------------------------------------------------------
# Status evidence constants and enums
# ---------------------------------------------------------------------------

class StatusEvidenceSourceKind(StrEnum):
    """Source mechanism for a status observation."""
    TRANSPORT_OBSERVATION = "transport-observation"
    MANAGED_HOOK = "managed-hook"
    MANAGED_PLUGIN = "managed-plugin"
    STRUCTURED_OUTPUT = "structured-output"


class StatusEvidenceSemanticStrength(StrEnum):
    """How strongly a status observation is semantically meaningful."""
    UNKNOWN = "unknown"
    INFERRED = "inferred"
    EXECUTION = "execution"


class StatusObserverState(StrEnum):
    """State of observer configuration and delivery."""
    READY = "ready"
    CONFIGURED = "configured"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    NEEDS_ACTION = "needs-action"


# ---------------------------------------------------------------------------
# StatusEvidence: bounded neutral observation of agent/turn status
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusEvidence:
    """A single bounded observation of session/request status.

    Carries canonical AG session/request correlation and bounded metadata
    only. No provider-native event names, raw payloads, or tool details.
    """

    status: str  # e.g. "model-thinking", "tool-calling", "waiting-permission"
    session_id: str  # AG session ID
    request_id: str | None  # AG request ID (or None for session-level events)
    correlation_id: str | None  # User-provided correlation ID
    observed_at: str  # ISO-8601 timestamp
    sequence: int | None  # Monotonic sequence within the turn
    source_kind: StatusEvidenceSourceKind
    semantic_strength: StatusEvidenceSemanticStrength = StatusEvidenceSemanticStrength.UNKNOWN
    verification_tier: str = "unknown"  # e.g. "unknown", "documented", "proven"

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not self.status:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="status must be a non-empty string",
                details={"status": self.status},
            )
        if not isinstance(self.session_id, str) or not self.session_id:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="session_id must be a non-empty string",
                details={"session_id": self.session_id},
            )
        if self.request_id is not None:
            if not isinstance(self.request_id, str) or not self.request_id:
                raise make_error(
                    prefix="VAL", component="TRANSPORT", number=1,
                    kind="harness-status-observer-validation",
                    message="request_id must be a non-empty string or None",
                    details={"request_id": self.request_id},
                )
        if not isinstance(self.observed_at, str) or not self.observed_at:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="observed_at must be a non-empty string (ISO-8601)",
            )
        if self.sequence is not None and (not isinstance(self.sequence, int) or self.sequence < 0):
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="sequence must be a non-negative integer or None",
                details={"sequence": self.sequence},
            )


# ---------------------------------------------------------------------------
# StatusObserverRequest and StatusObserverResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusObserverRequest:
    """Request to open a harness status observer.

    Carries project/provider context and acceptable status list.
    The resolver uses this to select a declared observer implementation.
    """

    project_root: str
    provider_id: str
    surface_id: str
    session_id: str
    request_id: str | None
    correlation_id: str | None = None
    accepted_statuses: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.project_root, str) or not self.project_root:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="project_root must be a non-empty string",
            )
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="provider_id must be a non-empty string",
            )
        if not isinstance(self.surface_id, str) or not self.surface_id:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="surface_id must be a non-empty string",
            )
        if not isinstance(self.session_id, str) or not self.session_id:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="session_id must be a non-empty string",
            )


@dataclass(frozen=True)
class StatusObserverResult:
    """Result of opening a status observer."""

    ok: bool
    supported: bool  # True only when full capability is confirmed
    state: StatusObserverState
    binding_id: str | None = None
    launch_environment: dict | None = None  # Mutations only through this
    managed_ids: list[str] = field(default_factory=list)
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.ok and not self.supported:
            # ok=true with supported=false is contradictory
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="ok=true requires supported=true",
            )
        if self.ok and self.binding_id is None:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="ok=true requires a non-None binding_id",
            )


# ---------------------------------------------------------------------------
# StatusObserverLease: opaque per-session observer binding
# ---------------------------------------------------------------------------

ObservationNormalizer = Callable[
    ["StatusObserverLease", list[any]],  # noqa: F821
    Awaitable[StatusEvidence | None]
]


@dataclass(frozen=True)
class StatusObserverLease:
    """An opaque per-session observer binding.

    Carries methods for observation normalization only; mutation state
    is owned by the agents runtime.
    """

    binding_id: str
    observe_transport: Callable[
        [any],  # TransportObservation  # noqa: F821
        StatusEvidence | None
    ]

    def __post_init__(self) -> None:
        if not isinstance(self.binding_id, str) or not self.binding_id:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="binding_id must be a non-empty string",
            )
        if not callable(self.observe_transport):
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="harness-status-observer-validation",
                message="observe_transport must be callable",
            )
