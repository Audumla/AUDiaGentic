"""Provider surface operations for session bindings.

Providers execute operations against resolved surfaces and return opaque refs.
They do not mutate AUDiaGentic session records or binding indexes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_binding import ProviderSessionRef, SessionOwnership


@dataclass(frozen=True)
class SessionMappingCapabilities:
    open_new: bool = False
    returns_opaque_ref: bool = False
    resume_by_ref: bool = False
    attach_existing: bool = False
    discover_existing: bool = False
    share_existing: bool = False
    replace_existing: bool = False
    concurrent_attachments: bool = False
    attach_while_turn_active: bool = False
    ref_scope: str = "unknown"
    ref_namespace: str = "provider-session-ref"
    requires_same_project: bool = True
    requires_same_execution_context: bool = True


@dataclass(frozen=True)
class ResolvedSessionSurface:
    provider_id: str
    surface_id: str
    surface_version: str | None
    identity_context_fingerprint: str
    execution_context_fingerprint: str
    capabilities: SessionMappingCapabilities


class SessionBindingSurface(Protocol):
    def open_session_binding(self, surface: ResolvedSessionSurface, **kwargs: Any) -> ProviderSessionRef: ...

    def attach_session_binding(
        self,
        surface: ResolvedSessionSurface,
        provider_session_ref: ProviderSessionRef,
        *,
        ownership: SessionOwnership,
        **kwargs: Any,
    ) -> ProviderSessionRef: ...

    def resume_session_binding(
        self,
        surface: ResolvedSessionSurface,
        provider_session_ref: ProviderSessionRef,
        **kwargs: Any,
    ) -> ProviderSessionRef: ...


def require_capability(surface: ResolvedSessionSurface, capability: str) -> None:
    if not bool(getattr(surface.capabilities, capability, False)):
        raise AudiaGenticError(
            code="CON-PROV-096",
            kind="providers",
            message="provider session binding operation is not supported by the resolved surface",
            details={
                "provider-id": surface.provider_id,
                "surface-id": surface.surface_id,
                "capability": capability,
            },
        )
