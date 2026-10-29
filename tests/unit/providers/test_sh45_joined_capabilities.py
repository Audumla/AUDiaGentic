"""SH45 additions on top of the strict claims tests (test_joined_session_capabilities.py).

``claimed`` (any claim) feeds readiness, while ``qualified`` (all five) gates the
declaration prerequisites; the resolved projection never carries claims whose
evidence is not validated.
"""
from __future__ import annotations

from pathlib import Path

from tests.unit.providers.test_session_surface_resolution import (  # noqa: F401 - autouse fixture
    _fake_descriptor,
    _isolate_registry,
)

from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.descriptors.registry import register
from audiagentic.components.providers.descriptors.session_surface_declarations import SessionSurfaceDeclaration
from audiagentic.components.providers.services.config.provider_config import set_provider_enabled
from audiagentic.components.providers.services.session.session_surface_resolution import resolve_session_surface
from audiagentic.foundation.transports.session_surface import (
    JoinedSessionCapabilities,
    PlatformEvidence,
    SurfaceResolutionOutcome,
    ValidationEvidence,
)
from audiagentic.runtime.system.platform import release_platform_name


def test_claimed_is_any_claim_and_qualified_is_all() -> None:
    assert not JoinedSessionCapabilities().claimed
    partial = JoinedSessionCapabilities(detach_safe=True)
    assert partial.claimed and not partial.qualified
    assert JoinedSessionCapabilities(True, True, True, True, True).qualified


def _register(tmp_path: Path, provider_id: str, *, validated: bool) -> None:
    evidence = ValidationEvidence(validated=True, reference="tests/fixtures/join.md") if validated \
        else ValidationEvidence()
    declaration = SessionSurfaceDeclaration(
        surface_id="acp", version_constraint=">=1.0", evidence=evidence,
        platforms=(PlatformEvidence(release_platform_name(), evidence),),
        joined_capabilities=JoinedSessionCapabilities(detach_safe=True),
    )
    register(_fake_descriptor(provider_id, session_surfaces=(declaration,)))
    set_provider_enabled(tmp_path, provider_id, enabled=True)


def test_resolved_projection_carries_validated_claims(tmp_path: Path) -> None:
    _register(tmp_path, "join-provider", validated=True)
    resolved = resolve_session_surface(tmp_path, "join-provider", SurfaceHint(surface_id="acp"))
    assert resolved.validation.outcome is SurfaceResolutionOutcome.SUPPORTED
    assert resolved.joined_capabilities == JoinedSessionCapabilities(detach_safe=True)


def test_unvalidated_claims_never_reach_the_projection(tmp_path: Path) -> None:
    _register(tmp_path, "unproven-provider", validated=False)
    resolved = resolve_session_surface(tmp_path, "unproven-provider", SurfaceHint(surface_id="acp"))
    assert resolved.validation.outcome is SurfaceResolutionOutcome.UNPROVEN
    assert not resolved.joined_capabilities.claimed
