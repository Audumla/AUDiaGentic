"""Foundation-neutral agent session transport contract (AS28 stage 1).

Defines frozen, scalar-safe value types and the :class:`AgentSessionTransport`
Protocol that any provider surface must implement. No ``components.*`` imports,
no provider-native payloads or IDs, no callables on dataclasses.

The module is intentionally lower-level than the canonical status contract
(AS19/AS21): it provides transport observations and control operations only;
state decisions belong to AS21.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.transports.session_binding import ProviderSessionRef

# ---------------------------------------------------------------------------
# Coded error constants (registered in foundation/error-resolutions.yaml)
# ---------------------------------------------------------------------------

ERR_TRANSPORT_INVALID_ACTION = "VAL-TRANSPORT-001"
ERR_TRANSPORT_INVALID_ATTRIBUTE_KEY = "VAL-TRANSPORT-002"
ERR_TRANSPORT_INVALID_ATTRIBUTE_VALUE = "VAL-TRANSPORT-003"
ERR_TRANSPORT_INVALID_CONTROL_PAYLOAD = "VAL-TRANSPORT-004"
ERR_TRANSPORT_INVALID_TEXT_BOUND = "VAL-TRANSPORT-005"
ERR_TRANSPORT_UNKNOWN_KIND = "VAL-TRANSPORT-006"

# ---------------------------------------------------------------------------
# Bounded ID / text constants
# ---------------------------------------------------------------------------

_MAX_ID_LENGTH = 256
_MAX_PROMPT_BODY_BYTES = 1_048_576  # 1 MiB
_MAX_OBSERVATION_ATTRIBUTE_KEYS = 16
_MAX_SINGLE_ATTRIBUTE_VALUE_BYTES = 4096  # 4 KiB per attribute value
_ALLOWED_CONTROL_PAYLOAD_KEYS = frozenset(
    {
        "permission",  # "allow" | "deny"
        "steer_text",  # append-only steer text
    }
)
_PERMISSION_VALUES = frozenset({"allow", "deny"})

# ---------------------------------------------------------------------------
# Canonical transport observation kinds (closed set)
# ---------------------------------------------------------------------------


class TransportObservationKind(StrEnum):
    """Bounded neutral observation vocabulary.

    Providers map native protocol frames to this closed set. Unknown or
    unmappable native events produce :attr:`TRANSPORT_UNKNOWN` — never a
    raw/native kind value leaking into the contract.
    """

    TURN_ACCEPTED = "turn-accepted"
    ACTIVITY = "activity"
    TOOL_REQUESTED = "tool-requested"
    TOOL_FINISHED = "tool-finished"
    PERMISSION_REQUESTED = "permission-requested"
    IN_PROGRESS = "in-progress"
    TERMINAL = "terminal"
    TRANSPORT_ERROR = "transport-error"
    TRANSPORT_CLOSED = "transport-closed"
    # Explicit bounded unknown: used when the provider cannot map a native
    # event to a canonical kind. Drop-safe for consumers; never carries
    # raw event name or payload.
    TRANSPORT_UNKNOWN = "transport-unknown"


# ---------------------------------------------------------------------------
# Bounded allowed attribute keys per observation kind
# ---------------------------------------------------------------------------

_ALLOWED_ATTRIBUTE_KEYS: Mapping[TransportObservationKind, frozenset[str]] = {
    TransportObservationKind.TURN_ACCEPTED: frozenset({"reason"}),
    TransportObservationKind.ACTIVITY: frozenset(
        {
            "model_activity",  # e.g. "generating", "thinking" — proven only
        }
    ),
    TransportObservationKind.TOOL_REQUESTED: frozenset(
        {
            "tool_call_id",
            "tool_status",
        }
    ),
    TransportObservationKind.TOOL_FINISHED: frozenset(
        {
            "tool_call_id",
            "tool_status",
            "reason",
        }
    ),
    TransportObservationKind.PERMISSION_REQUESTED: frozenset(
        {
            "tool_call_id",
        }
    ),
    TransportObservationKind.IN_PROGRESS: frozenset(
        {
            "model_activity",  # e.g. "generating", "thinking" — proven only
        }
    ),
    TransportObservationKind.TERMINAL: frozenset({"stop_reason", "error_code"}),
    TransportObservationKind.TRANSPORT_ERROR: frozenset({"error_code", "reason"}),
    TransportObservationKind.TRANSPORT_CLOSED: frozenset({}),
    # TRANSPORT_UNKNOWN: no attributes — by definition we don't know what to
    # carry. If the provider tried to include one, it would be an error.
    TransportObservationKind.TRANSPORT_UNKNOWN: frozenset({}),
}


# ---------------------------------------------------------------------------
# Correlation quality  (how well does the observation tie back to our turn?)
# ---------------------------------------------------------------------------


class CorrelationQuality(StrEnum):
    """How strongly an observation is correlated to the originating turn."""

    CORRELATED = "correlated"  # Native correlation id matches
    REQUEST_SCOPED = "request-scoped"  # Scoped to this prompt request, no native ref
    UNCERTAIN = "uncertain"  # Transport loss or ambiguous source


# ---------------------------------------------------------------------------
# Control actions and dispositions (AS28 stage 1)
# ---------------------------------------------------------------------------


class SessionControlAction(StrEnum):
    """Canonical session control actions the gateway may request.

    Closed set; new actions require a plan review (MA18). This is the
    canonical definition — also re-exported from session_surface for
    backward compatibility with AS29 surface resolution.
    """

    CANCEL_TURN = "cancel-turn"
    INTERRUPT_TURN = "interrupt-turn"
    STEER_TURN = "steer-turn"
    RESPOND_PERMISSION = "respond-permission"
    CLOSE_SESSION = "close-session"


class ControlDisposition(StrEnum):
    """Outcome of a control request. Never implies durable session state."""

    ACCEPTED = "accepted"
    UNSUPPORTED = "unsupported"
    ALREADY_TERMINAL = "already-terminal"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class SessionFailureDisposition(StrEnum):
    """What the session runtime should do after a turn raises.

    Most transports cannot safely continue after a turn-level failure and
    therefore terminate their session.  A provider with an explicit recovery
    state machine may retain the live session and accept a later turn.
    """

    RETAIN = "retain"
    TERMINATE = "terminate"


# ---------------------------------------------------------------------------
# Scalar type alias and validators
# ---------------------------------------------------------------------------

Scalar = str | int | float | bool | None


def _validate_id(value: str, name: str, max_len: int = _MAX_ID_LENGTH) -> None:
    """Validate an ID string is non-empty, bounded, and contains only safe chars."""
    if not isinstance(value, str):
        raise make_error(
            prefix="VAL",
            component="TRANSPORT",
            number=1,
            kind="transport-contract-validation",
            message=f"{name} must be a string",
            details={"field": name},
        )
    if not value:
        raise make_error(
            prefix="VAL",
            component="TRANSPORT",
            number=1,
            kind="transport-contract-validation",
            message=f"{name} must not be empty",
            details={"field": name},
        )
    if len(value) > max_len:
        raise make_error(
            prefix="VAL",
            component="TRANSPORT",
            number=5,
            kind="transport-contract-validation",
            message=f"{name} exceeds maximum length of {max_len}",
            details={"field": name, "length": len(value)},
        )


def _validate_scalar(value: Any, key: str) -> Scalar:
    """Validate and coerce a value to a scalar. Rejects callables, dicts, lists."""
    if callable(value) and not isinstance(value, (str, bool)):
        raise make_error(
            prefix="VAL",
            component="TRANSPORT",
            number=3,
            kind="transport-contract-validation",
            message=f"attribute {key!r} carries a callable value",
            details={"key": key},
        )
    if isinstance(value, (dict, list, tuple)):
        raise make_error(
            prefix="VAL",
            component="TRANSPORT",
            number=3,
            kind="transport-contract-validation",
            message=f"attribute {key!r} carries a composite value; only scalars allowed",
            details={"key": key},
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        if (
            isinstance(value, str)
            and len(value.encode("utf-8")) > _MAX_SINGLE_ATTRIBUTE_VALUE_BYTES
        ):
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=5,
                kind="transport-contract-validation",
                message=f"attribute {key!r} value exceeds {_MAX_SINGLE_ATTRIBUTE_VALUE_BYTES} bytes",
                details={"key": key, "byte-length": len(value.encode("utf-8"))},
            )
        return value
    raise make_error(
        prefix="VAL",
        component="TRANSPORT",
        number=3,
        kind="transport-contract-validation",
        message=f"attribute {key!r} carries non-scalar type {type(value).__name__}",
        details={"key": key, "type": type(value).__name__},
    )


def _validate_allowed_keys(
    keys: Mapping[str, Any],
    kind: TransportObservationKind,
) -> None:
    """Reject attribute keys not in the allowed set for this observation kind."""
    allowed = _ALLOWED_ATTRIBUTE_KEYS.get(kind, frozenset())
    for key in keys:
        if key not in allowed:
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=2,
                kind="transport-contract-validation",
                message=f"attribute {key!r} is not allowed for observation kind {kind.value}",
                details={"key": key, "kind": kind.value, "allowed": sorted(allowed)},
            )


# ---------------------------------------------------------------------------
# TransportObservation  (AS28 stage 1 — bounded neutral event)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportObservation:
    """A single bounded transport observation.

    Carries canonical AG session/turn IDs and a closed-set kind with
    constrained scalar attributes only. No provider session ref, raw event
    name/payload, prompt text, output, tool arguments/results, callables, or
    arbitrary maps.
    """

    ag_session_id: str
    turn_id: str | None
    sequence: int | None
    kind: TransportObservationKind
    observed_at: str
    correlation_quality: CorrelationQuality
    attributes: Mapping[str, Scalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_id(self.ag_session_id, "ag_session_id")
        if self.turn_id is not None:
            _validate_id(self.turn_id, "turn_id")
        if self.sequence is not None and (not isinstance(self.sequence, int) or self.sequence < 0):
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=3,
                kind="transport-contract-validation",
                message="sequence must be a non-negative integer or None",
                details={"value": self.sequence},
            )
        if not isinstance(self.observed_at, str) or not self.observed_at:
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=1,
                kind="transport-contract-validation",
                message="observed_at must be a non-empty string (ISO-8601)",
            )
        _validate_allowed_keys(self.attributes, self.kind)
        if len(self.attributes) > _MAX_OBSERVATION_ATTRIBUTE_KEYS:
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=2,
                kind="transport-contract-validation",
                message=f"too many attributes ({len(self.attributes)}); max {_MAX_OBSERVATION_ATTRIBUTE_KEYS}",
            )
        for key, value in self.attributes.items():
            _validate_scalar(value, key)


# ---------------------------------------------------------------------------
# SessionPrompt  (AS28 stage 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionPrompt:
    """A gateway prompt request for one turn.

    Contains only the turn id, prompt body text, and optional cancellation
    token/deadline. No provider-native framing or protocol details.
    """

    turn_id: str
    body: str
    cancel_token: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_id(self.turn_id, "turn_id")
        if not isinstance(self.body, str):
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=1,
                kind="transport-contract-validation",
                message="body must be a string",
            )
        if len(self.body.encode("utf-8")) > _MAX_PROMPT_BODY_BYTES:
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=5,
                kind="transport-contract-validation",
                message=f"prompt body exceeds {_MAX_PROMPT_BODY_BYTES} bytes",
                details={"byte-length": len(self.body.encode("utf-8"))},
            )


# ---------------------------------------------------------------------------
# SessionOpenResult  (AS28 stage 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionOpenResult:
    """Result of opening a transport session.

    ``ag_session_id`` is the canonical gateway-side session identifier.
    ``provider_session_ref`` is the protected provider-native identity when
    it is already known. Providers that receive an identity after ``open``
    publish it through the delayed binding sink.
    """

    ag_session_id: str
    provider_session_ref: ProviderSessionRef | None = field(default=None, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_id(self.ag_session_id, "ag_session_id")


# ---------------------------------------------------------------------------
# SessionTurnResult  (AS28 stage 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionTurnResult:
    """Bounded result of one prompt turn.

    Carries only the terminal stop reason, observed correlation quality, and
    counts — no raw events, output text, or provider-native details. Output
    delivery is the responsibility of the observation sink (AS21).
    """

    turn_id: str
    stop_reason: str | None
    observations_delivered: int
    dropped_observations: int
    correlation_quality: CorrelationQuality = CorrelationQuality.REQUEST_SCOPED
    error_code: str | None = None
    final_summary: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_id(self.turn_id, "turn_id")
        if self.stop_reason is not None:
            _validate_id(self.stop_reason, "stop_reason", max_len=128)
        if not isinstance(self.observations_delivered, int) or self.observations_delivered < 0:
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=3,
                kind="transport-contract-validation",
                message="observations_delivered must be a non-negative integer",
            )
        if not isinstance(self.dropped_observations, int) or self.dropped_observations < 0:
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=3,
                kind="transport-contract-validation",
                message="dropped_observations must be a non-negative integer",
            )


# ---------------------------------------------------------------------------
# SessionControlRequest  (AS28 stage 1 — canonical constrained payload)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionControlRequest:
    """A canonical control request with constrained payload.

    Supports only the five defined actions and their canonical payloads. No
    provider-native command/payload escape hatch. Unknown keys in ``payload``
    are rejected (default-deny).
    """

    ag_session_id: str
    turn_id: str | None
    action: SessionControlAction
    request_id: str = field(default_factory=lambda: "control-request")
    payload: Mapping[str, Scalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_id(self.ag_session_id, "ag_session_id")
        if self.turn_id is not None:
            _validate_id(self.turn_id, "turn_id")
        _validate_id(self.request_id, "request_id")
        # Check no-payload actions first — clearer error than key-not-allowed
        _NO_PAYLOAD_ACTIONS = frozenset(
            {
                SessionControlAction.CANCEL_TURN,
                SessionControlAction.INTERRUPT_TURN,
                SessionControlAction.CLOSE_SESSION,
            }
        )
        if self.action in _NO_PAYLOAD_ACTIONS and self.payload:
            raise make_error(
                prefix="VAL",
                component="TRANSPORT",
                number=4,
                kind="transport-contract-validation",
                message=f"{self.action.value} does not accept a payload",
                details={"action": self.action.value},
            )
        # Validate payload keys are from the allowed set
        for key in self.payload:
            if key not in _ALLOWED_CONTROL_PAYLOAD_KEYS:
                raise make_error(
                    prefix="VAL",
                    component="TRANSPORT",
                    number=4,
                    kind="transport-contract-validation",
                    message=f"control payload key {key!r} is not allowed; "
                    f"allowed: {sorted(_ALLOWED_CONTROL_PAYLOAD_KEYS)}",
                    details={"key": key, "allowed-keys": sorted(_ALLOWED_CONTROL_PAYLOAD_KEYS)},
                )
        # Validate payload values are scalars
        for key, value in self.payload.items():
            _validate_scalar(value, key)
        # Validate action-specific constraints
        if self.action == SessionControlAction.RESPOND_PERMISSION:
            perm = self.payload.get("permission")
            if not isinstance(perm, str):
                raise make_error(
                    prefix="VAL",
                    component="TRANSPORT",
                    number=4,
                    kind="transport-contract-validation",
                    message="respond-permission requires a 'permission' value of 'allow' or 'deny'",
                )
            if perm not in _PERMISSION_VALUES:
                raise make_error(
                    prefix="VAL",
                    component="TRANSPORT",
                    number=4,
                    kind="transport-contract-validation",
                    message=f"respond-permission 'permission' must be one of {_PERMISSION_VALUES}, got {perm!r}",
                    details={"value": perm},
                )
        if self.action == SessionControlAction.STEER_TURN:
            steer = self.payload.get("steer_text")
            if not isinstance(steer, str):
                raise make_error(
                    prefix="VAL",
                    component="TRANSPORT",
                    number=4,
                    kind="transport-contract-validation",
                    message="steer-turn requires a 'steer_text' string value",
                )


# ---------------------------------------------------------------------------
# SessionControlResult  (AS28 stage 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionControlResult:
    """Result of a control request. Never implies durable session state."""

    disposition: ControlDisposition
    correlation_quality: CorrelationQuality = CorrelationQuality.UNCERTAIN
    error_code: str | None = None


# ---------------------------------------------------------------------------
# ObservationSink  (AS28 stage 1)
# ---------------------------------------------------------------------------


class ObservationSink(Protocol):
    """Callable that receives bounded transport observations.

    Used by :meth:`AgentSessionTransport.prompt` to deliver observations
    to the gateway session pipeline without exposing raw provider events.
    """

    def __call__(self, observation: TransportObservation) -> Awaitable[None] | None: ...


# ---------------------------------------------------------------------------
# AgentSessionTransport  (AS28 stage 1 — Protocol)
# ---------------------------------------------------------------------------


class AgentSessionTransport(Protocol):
    """Provider-neutral agent session transport interface.

    All provider surfaces (ACP, Codex App Server, CLI/process-only, future
    native RPC) must implement this protocol. The implementation owns
    process lifecycle, protocol mapping, and bounded observation delivery.

    No provider-native types cross this boundary: only canonical foundation
    value types (:class:`SessionPrompt`, :class:`TransportObservation`, etc.)
    are used.
    """

    async def open(self) -> SessionOpenResult:
        """Open the transport session. Returns the canonical AG session id."""
        ...

    async def prompt(
        self,
        request: SessionPrompt,
        sink: ObservationSink,
    ) -> SessionTurnResult:
        """Run one turn with bounded observation delivery via *sink*."""
        ...

    async def control(
        self,
        request: SessionControlRequest,
    ) -> SessionControlResult:
        """Issue a canonical control action. No native escape hatch."""
        ...

    async def close(self) -> None:
        """Shut the session down. Idempotent; never raises on failure."""
        ...

    def is_alive(self) -> bool:
        """True while the transport is open and its child has not exited."""
        ...

    def turn_failure_disposition(self) -> SessionFailureDisposition:
        """Return the state-machine decision after the latest failed turn."""
        ...
