"""Strict joined-session readiness for one provider surface (SH46, slice of SH39).

Decides whether a surface may join a session a human already runs, from
static facts only: the installed implementation on the execution side, the
surface declaration (SH45), an implemented join adapter and exact positive
qualification evidence (SH53). No prompt is sent and no process is started
other than the descriptor's own version probe. Passive proof of the live
instance is SH47 and happens immediately before any effect.

Fail-closed rules from the SH39 review:
- an unknown or unparseable installed version, or an unparseable version
  constraint, never selects a declaration (no fallback to the constraint);
- missing inventory or evidence is UNPROVEN, never supported;
- a callable adapter factory is not proof: the adapter module must declare
  ``JOIN_ADAPTER`` and the evidence must name its exact digest;
- the platform is the inventory's, which runs where the session executes;
- the five declared booleans are claims; only claims the evidence proves
  count, and the mandatory set must all be proven.

Evidence capability vocabulary (SH53) for each claim:
  detach_safe -> safe-detach
  prompt_delivery, native_atomic_queue_admission -> conditional-admission
  correlated_terminal_output -> correlated-result
  human_concurrency_safe -> concurrent-human-use
Every join also needs passive-identity and existing-session-attach.
Mandatory: detach_safe, prompt_delivery, correlated_terminal_output, and
concurrency-safe admission (human_concurrency_safe, or a native atomic queue).
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from audiagentic.foundation.transports.session_surface import (
    JoinedSessionCapabilities,
    SurfaceResolutionOutcome,
)

from ..qualification import evidence as qualification_evidence
from .session_surface_resolution import _version_satisfies

EVIDENCE_CAPABILITY = {
    "detach_safe": "safe-detach",
    "prompt_delivery": "conditional-admission",
    "native_atomic_queue_admission": "conditional-admission",
    "correlated_terminal_output": "correlated-result",
    "human_concurrency_safe": "concurrent-human-use",
}
JOIN_PREREQUISITES = ("passive-identity", "existing-session-attach")
MANDATORY = ("detach_safe", "prompt_delivery", "correlated_terminal_output")
CONCURRENCY = ("human_concurrency_safe", "native_atomic_queue_admission")

_EXACT_VERSION = re.compile(r"\d+(?:\.\d+){1,3}")
_CONSTRAINT = re.compile(r"(>=|<=|>|<|==)?\s*\d+(?:\.\d+)*")


@dataclass(frozen=True)
class JoinAdapterInfo:
    """Declared by a join adapter module as ``JOIN_ADAPTER``."""

    adapter_id: str
    adapter_version: str
    native_schema_version: str
    # Read-only passive inspection of one live instance (SH47); None = cannot inspect.
    inspect_instance: Callable[[Any], Any] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class AdapterIdentity:
    adapter_id: str
    adapter_digest: str
    native_schema_version: str
    inspect_instance: Callable[[Any], Any] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class JoinReadiness:
    provider_id: str
    surface_id: str
    outcome: SurfaceResolutionOutcome
    reasons: tuple[str, ...] = ()
    platform: str | None = None
    executable_version: str | None = None
    executable_digest: str | None = None
    evidence_id: str | None = None
    endpoint_kind: str | None = None
    native_schema_version: str | None = None
    adapter: AdapterIdentity | None = field(default=None, compare=False, repr=False)
    proven: JoinedSessionCapabilities = JoinedSessionCapabilities()

    @property
    def ready(self) -> bool:
        return self.outcome is SurfaceResolutionOutcome.SUPPORTED


def adapter_identity(adapter_ref: str | None) -> AdapterIdentity | None:
    """The exact identity of an implemented join adapter, or None.

    The adapter_ref's module must declare ``JOIN_ADAPTER``; the digest covers
    that module's source file.
    """
    if not adapter_ref:
        return None
    from audiagentic.foundation.config.refs import resolve_ref

    try:
        module = inspect.getmodule(resolve_ref(adapter_ref))
    except Exception:  # noqa: BLE001 - an unresolvable adapter is simply not implemented
        return None
    info = getattr(module, "JOIN_ADAPTER", None)
    source = getattr(module, "__file__", None)
    if not isinstance(info, JoinAdapterInfo) or not source:
        return None
    return AdapterIdentity(info.adapter_id, qualification_evidence.file_digest(Path(source)),
                           info.native_schema_version, info.inspect_instance)


def resolve_join_readiness(
    provider_id: str,
    surface_id: str,
    *,
    facts: dict[str, Any] | None = None,
    adapter: AdapterIdentity | None = None,
    state_root: Path | None = None,
) -> JoinReadiness:
    """Static join readiness; every gap is a refusal with a compact reason.

    ``facts`` defaults to the execution-side inventory (SH53); ``adapter`` to
    the identity declared by the selected surface's adapter module.
    """
    from audiagentic.components.providers.descriptors.registry import get_descriptor

    def result(outcome: SurfaceResolutionOutcome, *reasons: str, **extra: Any) -> JoinReadiness:
        return JoinReadiness(provider_id, surface_id, outcome, tuple(reasons), **extra)

    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return result(SurfaceResolutionOutcome.UNAVAILABLE, "unknown-provider")
    facts = qualification_evidence.inventory(provider_id) if facts is None else facts
    platform, version, digest = facts.get("platform"), facts.get("executable-version"), facts.get("executable-digest")
    identity = {"platform": platform, "executable_version": version, "executable_digest": digest}
    if not digest:
        return result(SurfaceResolutionOutcome.UNAVAILABLE, "executable-not-found", **identity)
    if not version or not _EXACT_VERSION.fullmatch(version):
        return result(SurfaceResolutionOutcome.UNPROVEN, "installed-version-unknown", **identity)

    declared = [d for d in descriptor.session_surfaces if d.surface_id == surface_id]
    if not declared:
        return result(SurfaceResolutionOutcome.UNSUPPORTED, "surface-not-declared", **identity)
    if any(not _CONSTRAINT.fullmatch(d.version_constraint.strip()) for d in declared):
        return result(SurfaceResolutionOutcome.UNSUPPORTED, "unparseable-version-constraint", **identity)
    matching = [d for d in declared if _version_satisfies(version, d.version_constraint) is True]
    if len(matching) != 1:
        reason = "version-not-declared" if not matching else "ambiguous-version-declarations"
        return result(SurfaceResolutionOutcome.UNSUPPORTED, reason, **identity)
    declaration = matching[0]
    claims = declaration.joined_capabilities
    if not claims.claimed:
        return result(SurfaceResolutionOutcome.UNSUPPORTED, "join-not-declared", **identity)
    if not any(p.platform == platform and p.evidence.validated for p in declaration.platforms):
        return result(SurfaceResolutionOutcome.UNSUPPORTED, "platform-not-validated", **identity)

    adapter = adapter_identity(declaration.adapter_ref) if adapter is None else adapter
    if adapter is None:
        return result(SurfaceResolutionOutcome.UNSUPPORTED, "adapter-not-implemented", **identity)
    record = qualification_evidence.find_exact(
        provider_id=provider_id, surface_id=surface_id, platform=platform, executable_digest=digest,
        adapter_digest=adapter.adapter_digest, native_schema_version=adapter.native_schema_version,
        state_root=state_root,
    )
    if record is None:
        return result(SurfaceResolutionOutcome.UNPROVEN, "no-exact-evidence", **identity)
    identity["evidence_id"] = record["evidence-id"]
    identity["endpoint_kind"] = record["target"]["endpoint-kind"]
    identity["native_schema_version"] = adapter.native_schema_version
    identity["adapter"] = adapter
    if record["target"]["executable-version"] != version:
        return result(SurfaceResolutionOutcome.UNPROVEN, "evidence-version-mismatch", **identity)

    proven_names = qualification_evidence.proven_capabilities(record)
    missing_prerequisites = [name for name in JOIN_PREREQUISITES if name not in proven_names]
    proven = JoinedSessionCapabilities(**{
        field.name: getattr(claims, field.name) and EVIDENCE_CAPABILITY[field.name] in proven_names
        for field in fields(JoinedSessionCapabilities)
    })
    if missing_prerequisites:
        return result(SurfaceResolutionOutcome.UNSUPPORTED,
                      *(f"unproven-{name}" for name in missing_prerequisites), **identity)
    missing = [f"unproven-{name}" for name in MANDATORY if not getattr(proven, name)]
    if not any(getattr(proven, name) for name in CONCURRENCY):
        missing.append("unproven-concurrency-safe-admission")
    if missing:
        return result(SurfaceResolutionOutcome.UNSUPPORTED, *missing, proven=proven, **identity)
    return result(SurfaceResolutionOutcome.SUPPORTED, proven=proven, **identity)
