"""Passive proof of the exact live instance behind a joinable surface (SH47, slice of SH39).

SH46 decides from static facts whether a surface may join at all. This is the
second gate, run immediately before any effect and again on reconnect: it asks
the join adapter to observe the one instance the caller wants to join and
accepts it only if that instance is the qualified implementation:

- the process serving the endpoint runs the executable whose digest, version
  and native schema version the evidence names (the PATH binary is not
  evidence for the binary actually serving the human);
- the endpoint kind and the session reference are the requested ones;
- the instance is alive and reports a generation, and when the caller holds
  an expected generation (a binding made earlier) it must still match, so a
  restarted or replaced instance is refused rather than silently rejoined.

Inspection is read-only by contract: nothing here sends a prompt, installs
anything or starts a process. Any adapter error or malformed observation is a
refusal. The result carries the evidence id and the observed generation so
later fencing (SH48) can bind to exactly what was proven.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.transports.session_surface import SurfaceResolutionOutcome

from .join_readiness import JoinReadiness, resolve_join_readiness


@dataclass(frozen=True)
class InstanceQuery:
    """What to observe: an opaque endpoint locator and the session to join."""

    provider_id: str
    surface_id: str
    endpoint: str
    session_ref: str


@dataclass(frozen=True)
class InstanceObservation:
    """What the adapter saw. Scalars only; no handles or native payloads."""

    alive: bool
    executable_digest: str
    executable_version: str
    native_schema_version: str
    endpoint_kind: str
    session_ref: str
    generation: str


@dataclass(frozen=True)
class JoinInstanceProof:
    provider_id: str
    surface_id: str
    outcome: SurfaceResolutionOutcome
    reasons: tuple[str, ...] = ()
    evidence_id: str | None = None
    generation: str | None = None
    session_ref: str | None = None

    @property
    def proven(self) -> bool:
        return self.outcome is SurfaceResolutionOutcome.SUPPORTED


def inspect_join_instance(
    provider_id: str,
    surface_id: str,
    *,
    endpoint: str,
    session_ref: str,
    expected_generation: str | None = None,
    readiness: JoinReadiness | None = None,
    state_root: Path | None = None,
) -> JoinInstanceProof:
    """Prove one live instance is the qualified one, or refuse with reasons."""

    def refuse(outcome: SurfaceResolutionOutcome, *reasons: str, evidence_id: str | None = None) -> JoinInstanceProof:
        return JoinInstanceProof(provider_id, surface_id, outcome, tuple(reasons), evidence_id=evidence_id)

    if not endpoint or not session_ref:
        return refuse(SurfaceResolutionOutcome.UNSUPPORTED, "endpoint-and-session-required")
    ready = readiness or resolve_join_readiness(provider_id, surface_id, state_root=state_root)
    if not ready.ready or ready.adapter is None:
        return refuse(ready.outcome, "not-join-ready", *ready.reasons)
    inspector = ready.adapter.inspect_instance
    if inspector is None:
        return refuse(SurfaceResolutionOutcome.UNSUPPORTED, "adapter-cannot-inspect", evidence_id=ready.evidence_id)
    try:
        observed = inspector(InstanceQuery(provider_id, surface_id, endpoint, session_ref))
    except Exception:  # noqa: BLE001 - an inspection failure is a refusal, never a pass
        return refuse(SurfaceResolutionOutcome.UNAVAILABLE, "inspection-failed", evidence_id=ready.evidence_id)
    if not isinstance(observed, InstanceObservation) or not observed.generation:
        return refuse(SurfaceResolutionOutcome.UNPROVEN, "malformed-observation", evidence_id=ready.evidence_id)
    if not observed.alive:
        return refuse(SurfaceResolutionOutcome.UNAVAILABLE, "instance-not-alive", evidence_id=ready.evidence_id)

    mismatches = [
        reason for reason, same in (
            ("executable-digest-mismatch", observed.executable_digest == ready.executable_digest),
            ("executable-version-mismatch", observed.executable_version == ready.executable_version),
            ("schema-version-mismatch", observed.native_schema_version == ready.native_schema_version),
            ("endpoint-kind-mismatch", observed.endpoint_kind == ready.endpoint_kind),
            ("session-mismatch", observed.session_ref == session_ref),
        ) if not same
    ]
    if expected_generation is not None and observed.generation != expected_generation:
        mismatches.append("generation-changed")
    if mismatches:
        return refuse(SurfaceResolutionOutcome.UNPROVEN, *mismatches, evidence_id=ready.evidence_id)
    return JoinInstanceProof(provider_id, surface_id, SurfaceResolutionOutcome.SUPPORTED,
                             evidence_id=ready.evidence_id, generation=observed.generation,
                             session_ref=observed.session_ref)
