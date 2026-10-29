"""One Provider authority for joined sessions: matrix, registration, revalidation (SH48).

Everything is derived from the same two gates: static readiness (SH46) and the
passive proof of the live instance (SH47). Nothing here keeps state, so there
is no second registry to drift: a registration is a frozen value the caller
(the gateway) stores, and this module is the only place that decides whether
it may still be used.

- ``join_matrix`` reports every provider surface with its readiness outcome
  and compact reasons, for status and inventory.
- ``register_join`` returns a registration only when the surface is ready and
  the requested instance is proven; otherwise no registration exists.
- ``revalidate_join`` runs immediately before any effect and on reconnect. It
  re-resolves everything and refuses if the evidence, executable or instance
  generation changed or any gate no longer passes, so a registration whose
  basis moved is not routable.

Evidence and readiness are not authorization: a principal grant is checked by
the gateway separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.transports.session_surface import SurfaceResolutionOutcome

from ..qualification import evidence as qualification_evidence
from .join_proof import inspect_join_instance
from .join_readiness import AdapterIdentity, JoinReadiness, resolve_join_readiness


@dataclass(frozen=True)
class JoinRegistration:
    """What was proven at registration; the basis revalidation compares against."""

    provider_id: str
    surface_id: str
    endpoint: str
    session_ref: str
    evidence_id: str
    executable_digest: str
    executable_version: str
    generation: str


@dataclass(frozen=True)
class JoinDecision:
    """Result of registering or revalidating a join."""

    outcome: SurfaceResolutionOutcome
    reasons: tuple[str, ...] = ()
    registration: JoinRegistration | None = None

    @property
    def routable(self) -> bool:
        return self.outcome is SurfaceResolutionOutcome.SUPPORTED and self.registration is not None


@dataclass(frozen=True)
class JoinMatrixRow:
    provider_id: str
    surface_id: str
    outcome: SurfaceResolutionOutcome
    reasons: tuple[str, ...]


def join_matrix(*, state_root: Path | None = None, facts: dict[str, dict[str, Any]] | None = None,
                adapters: dict[tuple[str, str], AdapterIdentity] | None = None) -> tuple[JoinMatrixRow, ...]:
    """Readiness of every declared surface of every provider, from the one resolver.

    ``facts`` and ``adapters`` are test seams: per-provider inventory facts and
    per-surface adapter identities replace the live inventory and adapter lookup.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    rows: list[JoinMatrixRow] = []
    for provider_id, descriptor in sorted(all_descriptors().items()):
        surface_ids = sorted({surface.surface_id for surface in descriptor.session_surfaces})
        if not surface_ids:
            continue
        provider_facts = (facts or {}).get(provider_id) or qualification_evidence.inventory(provider_id)
        for surface_id in surface_ids:
            ready = resolve_join_readiness(
                provider_id, surface_id, facts=provider_facts,
                adapter=(adapters or {}).get((provider_id, surface_id)), state_root=state_root)
            rows.append(JoinMatrixRow(provider_id, surface_id, ready.outcome, ready.reasons))
    return tuple(rows)


def register_join(provider_id: str, surface_id: str, *, endpoint: str, session_ref: str,
                  state_root: Path | None = None, facts: dict[str, Any] | None = None,
                  adapter: AdapterIdentity | None = None) -> JoinDecision:
    """Prove the requested instance and return its registration, or refuse."""
    ready = resolve_join_readiness(provider_id, surface_id, facts=facts, adapter=adapter, state_root=state_root)
    return _decide(ready, endpoint, session_ref, expected_generation=None, state_root=state_root)


def revalidate_join(registration: JoinRegistration, *, state_root: Path | None = None,
                    facts: dict[str, Any] | None = None, adapter: AdapterIdentity | None = None) -> JoinDecision:
    """Immediately before an effect or on reconnect: is the registration still valid?

    Refuses with ``evidence-changed`` / ``executable-changed`` /
    ``generation-changed`` when the basis moved, and with the underlying
    reasons when a gate fails. The result is never partially trusted.
    """
    ready = resolve_join_readiness(registration.provider_id, registration.surface_id, facts=facts,
                                   adapter=adapter, state_root=state_root)
    if ready.ready and ready.evidence_id != registration.evidence_id:
        return JoinDecision(SurfaceResolutionOutcome.UNPROVEN, ("evidence-changed",))
    if ready.ready and ready.executable_digest != registration.executable_digest:
        return JoinDecision(SurfaceResolutionOutcome.UNPROVEN, ("executable-changed",))
    return _decide(ready, registration.endpoint, registration.session_ref,
                   expected_generation=registration.generation, state_root=state_root)


def _decide(ready: JoinReadiness, endpoint: str, session_ref: str, *, expected_generation: str | None,
            state_root: Path | None) -> JoinDecision:
    proof = inspect_join_instance(ready.provider_id, ready.surface_id, endpoint=endpoint, session_ref=session_ref,
                                  expected_generation=expected_generation, readiness=ready, state_root=state_root)
    if not proof.proven:
        return JoinDecision(proof.outcome, proof.reasons)
    return JoinDecision(
        SurfaceResolutionOutcome.SUPPORTED,
        registration=JoinRegistration(
            ready.provider_id, ready.surface_id, endpoint, session_ref, proof.evidence_id or "",
            ready.executable_digest or "", ready.executable_version or "", proof.generation or ""))
