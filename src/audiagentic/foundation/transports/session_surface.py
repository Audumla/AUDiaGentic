"""Neutral foundation value types for resolved session-surface capability manifests.

AS29 stage 1: frozen, scalar-only metadata describing what a provider surface can
do. No callable, command, config path, raw protocol identifier, secret, or native
payload. No ``components.*`` imports.

This module does NOT provide a runtime resolver — that belongs to AS29/AS30
provider contracts and services. These value types are the immutable shape agents
consume once a surface has been resolved.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

# Re-export canonical control action from agent_session (AS28 stage 1).
# session_surface uses this for ResolvedSessionSurface.controls; the
# type-only reference avoids duplication while keeping backward-compatible
# imports for provider-side consumers.
from .agent_session import SessionControlAction

# ---------------------------------------------------------------------------
# Identity operations  (AS29 step 1 + RV717 §1)
# ---------------------------------------------------------------------------


class SessionIdentityOperation(StrEnum):
    """Provider session lifecycle operations the gateway may request."""

    OPEN = "open"
    ATTACH_EXISTING = "attach-existing"
    RESUME_BY_REF = "resume-by-ref"
    DISCOVER = "discover"


class ControlSupport(StrEnum):
    """Whether a control action or identity operation is declared supported."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Ownership modes  (AS29 step 3 / AS30)
# ---------------------------------------------------------------------------


class SessionOwnershipMode(StrEnum):
    OWNED = "owned"
    ADOPTED = "adopted"
    EXTERNAL = "external"


# ---------------------------------------------------------------------------
# Lifecycle source and installation  (AS29 step 3)
# ---------------------------------------------------------------------------


class LifecycleSource(StrEnum):
    """Where lifecycle observations originate."""

    TRANSPORT = "transport"
    HOOK = "hook"
    PLUGIN = "plugin"
    NATIVE_API = "native-api"
    STRUCTURED_OUTPUT = "structured-output"
    NONE = "none"


class LifecycleInstallation(StrEnum):
    """How lifecycle observation is installed at the provider side."""

    NONE = "none"
    MANAGED_HOOK = "managed-hook"
    MANAGED_PLUGIN = "managed-plugin"
    STRUCTURED_OUTPUT = "structured-output"


# ---------------------------------------------------------------------------
# Content channels  (AS29 step 3)
# ---------------------------------------------------------------------------


class ContentChannelId(StrEnum):
    ASSISTANT_TEXT = "assistant-text"
    ASSISTANT_FINAL = "assistant-final"
    TOOL_SUMMARY = "tool-summary"


# ---------------------------------------------------------------------------
# Validation / evidence  (AS67 — simplified from O0-O4 ladder)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationEvidence:
    """Minimal proof that a surface's declared behavior is real.

    Replaces the over-specified SurfaceValidationState + EffectiveObservationLevel
    ladder. A URL or internal doc/test path where validation can be verified,
    plus a simple boolean indicating whether it has actually been proven.
    """

    validated: bool = False
    reference: str = ""  # URL preferred; internal doc/test path acceptable

    def __post_init__(self) -> None:
        if self.validated and not self.reference.strip():
            raise ValueError("ValidationEvidence.reference must be non-empty when validated=True")


# ---------------------------------------------------------------------------
# Surface ref  (AS29 step 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionSurfaceRef:
    """Immutable surface identifier. Provider + surface id + resolved version."""

    provider_id: str
    surface_id: str
    resolved_version: str

    def __post_init__(self) -> None:
        for name in ("provider_id", "surface_id", "resolved_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"SessionSurfaceRef.{name} must be a non-empty string")


# ---------------------------------------------------------------------------
# Mapping facts  (RV717 §1 — subsume operation-neutral SessionMappingCapabilities)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionMappingFacts:
    """Operation-neutral identity and mapping facts that AS30 needs for binding.

    These replace the standalone :class:`SessionMappingCapabilities` fields so
    AS30 does not trigger a second contract migration (RV717 §1).
    """

    ref_scope: str = "unknown"
    ref_namespace: str = "provider-session-ref"
    requires_same_project: bool = True
    requires_same_execution_context: bool = True
    concurrent_attachments: bool = False
    attach_while_turn_active: bool = False
    share_existing: bool = False
    replace_existing: bool = False


# ---------------------------------------------------------------------------
# Identity capabilities  (AS29 step 1 + RV717 §1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionIdentityCapabilities:
    """Operation-level identity support and ownership constraints.

    ``identity_operations`` maps each :class:`SessionIdentityOperation` to its
    declared :class:`ControlSupport`.  Unknown operations default to
    :attr:`ControlSupport.UNSUPPORTED`.
    """

    identity_operations: Mapping[SessionIdentityOperation, ControlSupport] = field(
        default_factory=dict,
    )
    ownership_modes: tuple[SessionOwnershipMode, ...] = ()
    mapping_facts: SessionMappingFacts = field(default_factory=SessionMappingFacts)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identity_operations",
            MappingProxyType(self.identity_operations),
        )

    def operation_supported(self, op: SessionIdentityOperation) -> bool:
        return self.identity_operations.get(op) == ControlSupport.SUPPORTED

    def supports_ownership(self, mode: SessionOwnershipMode) -> bool:
        return mode in self.ownership_modes


# ---------------------------------------------------------------------------
# Lifecycle observation capabilities  (AS29 step 1 + step 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleObservationCapabilities:
    source: LifecycleSource = LifecycleSource.NONE
    installation: LifecycleInstallation = LifecycleInstallation.NONE
    correlation_id_supported: bool = False
    event_ordering_guaranteed: bool = False
    source_idempotency: bool = False


# ---------------------------------------------------------------------------
# Content channel  (AS29 step 3 — bounded)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentChannelCapability:
    """A single bounded content channel. Must carry byte/event limits."""

    channel: ContentChannelId
    max_bytes: int = 0
    max_events: int = 0

    def __post_init__(self) -> None:
        if self.max_bytes < 0 or self.max_events < 0:
            raise ValueError("ContentChannelCapability bounds must be non-negative")


# ---------------------------------------------------------------------------
# Content stream capabilities  (AS29 step 1 + step 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentStreamCapabilities:
    channels: tuple[ContentChannelCapability, ...] = ()

    def has_channel(self, channel_id: ContentChannelId) -> bool:
        return any(c.channel == channel_id for c in self.channels)


# ---------------------------------------------------------------------------
# Platform evidence  (AS29 step 11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlatformEvidence:
    """Per-platform validation evidence record.

    ``evidence`` replaces the former (validation_state, effective_level) pair;
    tool_version and probe_artifact are retained as descriptive metadata only.
    """

    platform: str  # e.g. "windows-amd64", "linux-amd64"
    evidence: ValidationEvidence = field(default_factory=ValidationEvidence)
    tool_version: str = ""
    probe_artifact: str = ""


# ---------------------------------------------------------------------------
# Surface validation  (AS29 step 1 + step 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SurfaceValidation:
    evidence: ValidationEvidence = field(default_factory=ValidationEvidence)
    platforms: tuple[PlatformEvidence, ...] = ()


# ---------------------------------------------------------------------------
# Resolved session surface  (AS29 step 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedSessionSurface:
    """Immutable snapshot of a resolved provider session-surface manifest.

    Contains only booleans, enums, and scalar limits — no callable, command,
    config path, raw protocol identifier, secret, or native payload.

    This is the *foundation* value type. The AS30 provider-contract surface
    in ``providers/contracts/session_binding.py`` is a distinct type;
    do not conflate the two.
    """

    ref: SessionSurfaceRef
    identity: SessionIdentityCapabilities
    controls: Mapping[SessionControlAction, ControlSupport] = field(
        default_factory=dict,
    )
    lifecycle: LifecycleObservationCapabilities = field(
        default_factory=LifecycleObservationCapabilities,
    )
    content: ContentStreamCapabilities = field(
        default_factory=ContentStreamCapabilities,
    )
    validation: SurfaceValidation = field(
        default_factory=SurfaceValidation,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "controls",
            MappingProxyType(self.controls),
        )

    def control_supported(self, action: SessionControlAction) -> bool:
        return self.controls.get(action) == ControlSupport.SUPPORTED


# ---------------------------------------------------------------------------
# Prepared session transport  (AS29 step 5 — slice 5a)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedSessionTransport:
    """Typed result of session transport preparation with resolved surface.

    Carries the transport launch, the same frozen surface snapshot used to
    determine it, and an effective provider reference. No descriptor/adapter/
    protocol/native values are exposed.

    ``transport`` is ``None`` when the resolved surface is unsupported —
    callers must inspect ``surface.validation.state`` before using the
    transport.

    When ``transport`` is ``None`` because preparation itself failed (rather
    than the surface being declared unsupported), ``unavailable_code`` and
    ``unavailable_message`` carry the classification. Both are plain scalars:
    the registered error code and its curated message. Structured ``details``
    are deliberately not carried here — they may hold paths, so they are
    logged at the failure site instead.
    """

    surface: ResolvedSessionSurface = field(repr=False)
    effective_provider_ref: SessionSurfaceRef = field(repr=False)
    transport: Any = None
    unavailable_code: str | None = None
    unavailable_message: str | None = None
    # Paths (relative to the request's runtime root) the provider considers
    # its own durable session state -- e.g. pi's native session .jsonl files.
    # A resolved surface with resume-by-ref supported should populate this so
    # SessionRuntime's close-time cleanup can preserve exactly this state
    # instead of deleting the whole isolated runtime root, which would make
    # resume-by-ref impossible regardless of any other resume machinery.
    # Empty for providers with no local durable state to preserve (e.g.
    # gpt-auto, whose session lives in the browser, not on local disk).
    runtime_preserve_relpaths: tuple[str, ...] = ()
