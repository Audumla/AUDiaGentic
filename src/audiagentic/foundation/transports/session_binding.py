"""Foundation-neutral session binding contract (AS30 stage-1).

Defines frozen, scalar-safe value types for provider session bindings and
mapping capabilities. No components.agents or components.providers imports.
ProviderSessionRef is protected/opaque; binding identity is scoped by AS29.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from audiagentic.foundation.contracts.errors import make_error


class BindingRelation(StrEnum):
    """How an AG session relates to a provider session."""

    OPENED = "opened"  # AG opened a new provider session
    ATTACHED = "attached"  # AG attached to an existing provider session
    RESUMED_FROM = "resumed-from"  # AG resumed from a prior binding
    REPLACED = "replaced"  # AG deliberately opened to replace a prior binding


class SessionOwnership(StrEnum):
    """Who owns the provider session lifecycle."""

    OWNED = "owned"  # AG owns it; gateway controls close/termination
    EXTERNAL = "external"  # External system owns it; non-AG close detaches only
    ADOPTED = "adopted"  # Authority transferred; follow transferred lifecycle


class SessionMappingCapability(StrEnum):
    """Operation capabilities declared by a resolved session surface."""

    # Open/close operations
    OPEN_NEW = "open-new"
    CLOSE_SESSION = "close-session"

    # Resume operations
    RESUME_BY_REF = "resume-by-ref"

    # Attach/discover operations
    ATTACH_EXISTING = "attach-existing"
    DISCOVER_EXISTING = "discover-existing"
    SHARE_EXISTING = "share-existing"

    # Replacement operations
    REPLACE_EXISTING = "replace-existing"

    # Concurrency and timing
    CONCURRENT_ATTACHMENTS = "concurrent-attachments"
    ATTACH_WHILE_TURN_ACTIVE = "attach-while-turn-active"


@dataclass(frozen=True)
class ProviderSessionRef:
    """Opaque protected reference to a provider session.

    The value is intentionally opaque: no parsing, logging, path use,
    filename use, display, or cross-surface reuse. Redacted in repr().
    """

    value: str = field(repr=False)

    def __repr__(self) -> str:
        """Redact the opaque value in repr()."""
        return "ProviderSessionRef(***)"

    def __str__(self) -> str:
        """Redact the opaque value in str()."""
        return "ProviderSessionRef(***)"

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="session-binding-validation",
                message="provider session ref value must be a non-empty string",
            )


@dataclass(frozen=True)
class SessionBindingIntent:
    """Intent for a session binding operation."""

    relation: BindingRelation
    ownership: SessionOwnership
    prior_binding_id: str | None = None


@dataclass(frozen=True)
class SessionMappingCapabilities:
    """Capabilities declared for a session surface's mapping operations.

    Unknown capabilities default to unsupported (safe-fail). All boolean
    fields represent what the surface has proven/declared.
    """

    # Open/close
    open_new: bool = False
    returns_opaque_ref: bool = False
    close_session: bool = False

    # Resume
    resume_by_ref: bool = False

    # Attach/discover
    attach_existing: bool = False
    discover_existing: bool = False
    share_existing: bool = False

    # Replace
    replace_existing: bool = False

    # Concurrency and timing
    concurrent_attachments: bool = False
    attach_while_turn_active: bool = False

    # Identity requirements
    requires_same_project: bool = False
    requires_same_execution_context: bool = False

    # Ref identity scoping
    ref_namespace: str = "unknown"  # e.g. "session-id", "thread-id", "account-id"

    def __post_init__(self) -> None:
        # open_new must be paired with returns_opaque_ref
        if self.open_new and not self.returns_opaque_ref:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="session-binding-validation",
                message="open_new capability requires returns_opaque_ref",
            )
        # resume_by_ref requires returns_opaque_ref to make sense
        if self.resume_by_ref and not self.returns_opaque_ref:
            raise make_error(
                prefix="VAL", component="TRANSPORT", number=1,
                kind="session-binding-validation",
                message="resume_by_ref capability requires returns_opaque_ref",
            )

    def supports(self, capability: SessionMappingCapability) -> bool:
        """Check if this surface supports a specific capability."""
        return bool(getattr(self, capability.value.replace("-", "_"), False))
