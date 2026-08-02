"""Descriptor-local session-surface declarations for ProviderDescriptor.

AS29 stage 2: typed, validated declaration objects parsed from provider YAML.
These carry an ``adapter_ref`` (descriptor-local dotted path) that must NOT
leak into the foundation :class:`ResolvedSessionSurface`. Validation runs at
loader/build time; adapter callables are *not* resolved here.

Error codes:
    VAL-PCAP-011 — session-surface declaration validation failures
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

_T = TypeVar("_T", bound=enum.Enum)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    ContentChannelCapability,
    ContentChannelId,
    ControlSupport,
    LifecycleInstallation,
    LifecycleSource,
    PlatformEvidence,
    SessionControlAction,
    SessionIdentityOperation,
    SessionMappingFacts,
    SessionOwnershipMode,
    ValidationEvidence,
)

# ---------------------------------------------------------------------------
# Descriptor-local declaration type (carries adapter_ref — NOT in foundation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionSurfaceDeclaration:
    """One session-surface declaration parsed from provider YAML.

    This is the *descriptor-local* representation. The ``adapter_ref`` field
    is a dotted module path string resolved later by the provider-resolver;
    it must never appear in :class:`ResolvedSessionSurface`.
    """

    surface_id: str
    version_constraint: str
    # Identity operations map  (foundation enums)
    identity_operations: Mapping[SessionIdentityOperation, ControlSupport] = field(
        default_factory=dict,
    )
    ownership_modes: tuple[SessionOwnershipMode, ...] = ()
    mapping_facts: SessionMappingFacts = field(default_factory=SessionMappingFacts)
    # Control actions map (foundation enums)
    controls: Mapping[SessionControlAction, ControlSupport] = field(
        default_factory=dict,
    )
    # Lifecycle observation declaration
    lifecycle_source: LifecycleSource = LifecycleSource.NONE
    lifecycle_installation: LifecycleInstallation = LifecycleInstallation.NONE
    correlation_id_supported: bool = False
    event_ordering_guaranteed: bool = False
    source_idempotency: bool = False
    # Content channels (bounded, foundation enums)
    content_channels: tuple[ContentChannelCapability, ...] = ()
    # Validation / platform evidence (AS67 — simplified)
    evidence: ValidationEvidence = field(default_factory=ValidationEvidence)
    platforms: tuple[PlatformEvidence, ...] = ()
    # Descriptor-local adapter reference — a dotted path string, NOT resolved.
    # This field must not appear in ResolvedSessionSurface (foundation type).
    adapter_ref: str | None = None


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _error(message: str, **details: object) -> AudiaGenticError:
    return AudiaGenticError(
        code="VAL-PCAP-011",
        kind="providers",
        message=message,
        details=details or None,
    )


# Pre-computed enum value sets for YAML string→enum mapping
_SURFACE_IDENTITY_OP_VALUES = {op.value for op in SessionIdentityOperation}
_CONTROL_SUPPORT_VALUES = {v.value for v in ControlSupport}
_CONTROL_ACTION_VALUES = {a.value for a in SessionControlAction}
_OWNERSHIP_MODE_VALUES = {m.value for m in SessionOwnershipMode}
_LIFECYCLE_SOURCE_VALUES = {s.value for s in LifecycleSource}
_LIFECYCLE_INSTALLATION_VALUES = {i.value for i in LifecycleInstallation}
_CONTENT_CHANNEL_VALUES = {c.value for c in ContentChannelId}


# Mapping enum string values → enum members
_SURFACE_IDENTITY_OP_MAP = {op.value: op for op in SessionIdentityOperation}
_CONTROL_SUPPORT_MAP = {v.value: v for v in ControlSupport}
_CONTROL_ACTION_MAP = {a.value: a for a in SessionControlAction}
_OWNERSHIP_MODE_MAP = {m.value: m for m in SessionOwnershipMode}
_LIFECYCLE_SOURCE_MAP = {s.value: s for s in LifecycleSource}
_LIFECYCLE_INSTALLATION_MAP = {i.value: i for i in LifecycleInstallation}
_CONTENT_CHANNEL_MAP = {c.value: c for c in ContentChannelId}


def _parse_enum(
    raw: Any,
    allowed_values: Set[str],
    map_dict: dict[str, _T],
    field_name: str,
) -> _T:
    """Validate a raw value is a known enum string and return the member."""
    if isinstance(raw, enum.Enum) and raw in map_dict.values():
        return cast(_T, raw)
    if not isinstance(raw, str) or raw not in allowed_values:
        raise _error(
            f"invalid {field_name} value",
            field=field_name,
            value=raw,
            allowed=list(sorted(allowed_values)),
        )
    return map_dict[raw]


def _validate_declarations(declarations: Sequence[SessionSurfaceDeclaration]) -> None:
    """Validate a collection of session-surface declarations.

    Rules:
        1. No duplicate (surface_id, version_constraint) pairs.
        2. Non-validated effective O2/O3/O4 is rejected — validation_state must
           be VALIDATED when effective_level >= O2.
        3. Validated declaration with no platform evidence is rejected.
        4. Any declared content channel with zero/absent byte AND event bound
           is rejected (both max_bytes == 0 and max_events == 0).
        5. Managed-hook/plugin lifecycle installation without a nonempty
           adapter_ref is rejected.
    """
    seen_keys: set[tuple[str, str]] = set()

    for decl in declarations:
        # Rule 1: duplicate (surface_id, version_constraint)
        key = (decl.surface_id, decl.version_constraint)
        if key in seen_keys:
            raise _error(
                "duplicate session-surface declaration key",
                surface_id=decl.surface_id,
                version_constraint=decl.version_constraint,
            )
        seen_keys.add(key)

        # Rule 2: controls or content channels require validated=True
        if not decl.evidence.validated and (decl.controls or decl.content_channels):
            raise _error(
                "controls or content channels require evidence.validated=True",
                surface_id=decl.surface_id,
                version_constraint=decl.version_constraint,
            )

        # Rule 3: validated with no platform evidence
        if decl.evidence.validated and not decl.platforms:
            raise _error(
                "validated session surface requires at least one PlatformEvidence",
                surface_id=decl.surface_id,
                version_constraint=decl.version_constraint,
            )

        # Rule 3b: validated parent requires at least one platform also validated
        # (local probe evidence). Unvalidated platforms under a validated parent
        # are allowed — they represent vendor-supported platforms without local
        # probe evidence yet. Cross-platform borrowing of proof is not allowed;
        # the resolver enforces that validated claims require inventory proof.
        if decl.evidence.validated:
            has_validated_platform = any(pe.evidence.validated for pe in decl.platforms)
            if not has_validated_platform:
                raise _error(
                    "validated session surface requires at least one validated platform",
                    surface_id=decl.surface_id,
                    version_constraint=decl.version_constraint,
                )

        # Rule 4: content channel with zero/absent bounds
        for ch in decl.content_channels:
            if ch.max_bytes == 0 and ch.max_events == 0:
                raise _error(
                    "content channel requires nonzero byte or event bound",
                    surface_id=decl.surface_id,
                    version_constraint=decl.version_constraint,
                    channel=ch.channel.value,
                )

        # Rule 5: managed-hook/plugin without adapter_ref
        if decl.lifecycle_installation in (
            LifecycleInstallation.MANAGED_HOOK,
            LifecycleInstallation.MANAGED_PLUGIN,
        ):
            if not decl.adapter_ref or not str(decl.adapter_ref).strip():
                raise _error(
                    "managed-hook/plugin lifecycle requires nonempty adapter_ref",
                    surface_id=decl.surface_id,
                    version_constraint=decl.version_constraint,
                    lifecycle_installation=decl.lifecycle_installation.value,
                )


def validate_session_surface_declarations(
    declarations: Sequence[SessionSurfaceDeclaration],
) -> None:
    """Public entry-point for validating session-surface declarations."""
    _validate_declarations(declarations)
