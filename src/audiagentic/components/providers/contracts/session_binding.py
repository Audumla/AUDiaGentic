"""Provider surface operations for session bindings.

Providers execute operations against resolved surfaces and return opaque refs.
They do not mutate AUDiaGentic session records or binding indexes.

``SessionMappingCapabilities`` is the authoritative foundation type from
``foundation.transports.session_binding`` — do not duplicate it here.
The ``BindingResolutionContext`` carries only the fields the provider surface
operation layer needs; it is NOT a substitute for ``ResolvedSessionSurface``
from the AS29 session-surface snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_binding import (
    ProviderSessionRef,
    SessionMappingCapabilities,
    SessionOwnership,
)


@dataclass(frozen=True)
class BindingResolutionContext:
    """Minimal surface context for capability-gated binding operations.

    Carries only the fields needed by provider surface operation adapters
    to validate and execute a binding operation. This is NOT the full AS29
    ``ResolvedSessionSurface`` snapshot — use the foundation type for that.
    """

    provider_id: str
    surface_id: str
    surface_version: str | None
    identity_context_fingerprint: str
    execution_context_fingerprint: str
    capabilities: SessionMappingCapabilities


class SessionBindingSurface(Protocol):
    def open_session_binding(self, context: BindingResolutionContext, **kwargs: Any) -> ProviderSessionRef: ...

    def attach_session_binding(
        self,
        context: BindingResolutionContext,
        provider_session_ref: ProviderSessionRef,
        *,
        ownership: SessionOwnership,
        **kwargs: Any,
    ) -> ProviderSessionRef: ...

    def resume_session_binding(
        self,
        context: BindingResolutionContext,
        provider_session_ref: ProviderSessionRef,
        **kwargs: Any,
    ) -> ProviderSessionRef: ...


def require_capability(context: BindingResolutionContext, capability: str) -> None:
    if not bool(getattr(context.capabilities, capability, False)):
        raise AudiaGenticError(
            code="CON-PROV-096",
            kind="providers",
            message="provider session binding operation is not supported by the resolved surface",
            details={
                "provider-id": context.provider_id,
                "surface-id": context.surface_id,
                "capability": capability,
            },
        )
