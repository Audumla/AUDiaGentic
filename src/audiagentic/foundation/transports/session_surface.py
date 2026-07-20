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
# Validation / evidence  (AS29 step 3 + RV717)
# ---------------------------------------------------------------------------

class SurfaceValidationState(StrEnum):
    DECLARED = "declared"
    PROBE_REQUIRED = "probe-required"
    VALIDATED = "validated"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"


class EffectiveObservationLevel(StrEnum):
    O0 = "O0"
    O1 = "O1"
    O2 = "O2"
    O3 = "O3"
    O4 = "O4"

    @property
    def numeric(self) -> int:
        """Numeric tier for ceiling arithmetic (RV717 validation rule)."""
        return int(self.value[1:]) if len(self.value) > 1 else 0


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
            raise ValueError(
                "ContentChannelCapability bounds must be non-negative"
            )


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
    """Per-platform validation and effective-level record."""

    platform: str  # e.g. "windows-amd64", "linux-amd64"
    tool_version: str = ""
    probe_artifact: str = ""
    validation_state: SurfaceValidationState = SurfaceValidationState.DECLARED
    effective_level: EffectiveObservationLevel = EffectiveObservationLevel.O0


# ---------------------------------------------------------------------------
# Surface validation  (AS29 step 1 + step 3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SurfaceValidation:
    state: SurfaceValidationState = SurfaceValidationState.DECLARED
    effective_level: EffectiveObservationLevel = EffectiveObservationLevel.O0
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
    """

    surface: ResolvedSessionSurface = field(repr=False)
    effective_provider_ref: SessionSurfaceRef = field(repr=False)
    transport: Any = None
