"""SH45: typed joined-session capability declarations, all unsupported by default.

Claims parse strictly through the existing session-surface loader, are only
accepted on surfaces that can attach to an external session with an exact
mapping and validated evidence, and reach the resolved projection only when
the evidence is validated. No shipped provider claims a join yet.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.providers.test_session_surface_declarations import (
    _min_valid_descriptor_data,
    _valid_surface_data,
)
from tests.unit.providers.test_session_surface_resolution import (  # noqa: F401 - autouse fixture
    _fake_descriptor,
    _isolate_registry,
)

from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.descriptors.loader import PROVIDER_SPEC
from audiagentic.components.providers.descriptors.registry import register
from audiagentic.components.providers.services.config.provider_config import set_provider_enabled
from audiagentic.components.providers.services.session.session_surface_resolution import (
    resolve_session_surface,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    JoinedSessionCapabilities,
    PlatformEvidence,
    SurfaceResolutionOutcome,
    ValidationEvidence,
)
from audiagentic.runtime.system.platform import release_platform_name

ALL_CLAIMS = {name: True for name in JoinedSessionCapabilities.__dataclass_fields__}


def _joinable_surface(**overrides) -> dict:
    """A surface that satisfies every prerequisite for a joined claim."""
    return _valid_surface_data(**{
        "identity_operations": {"open": "supported", "attach-existing": "supported"},
        "ownership_modes": ["owned", "external"],
        "mapping_facts": {"ref_scope": "provider-session"},
        **overrides,
    })


def _build(surface: dict):
    data = _min_valid_descriptor_data()
    data["session_surfaces"] = [surface]
    return PROVIDER_SPEC.build(data).session_surfaces[0]


def test_defaults_are_all_unsupported() -> None:
    capabilities = JoinedSessionCapabilities()
    assert not capabilities.claimed
    assert not any(getattr(capabilities, name) for name in JoinedSessionCapabilities.__dataclass_fields__)
    assert _build(_valid_surface_data()).joined_capabilities == JoinedSessionCapabilities()


def test_value_type_is_frozen_and_strict() -> None:
    with pytest.raises(ValueError, match="must be a bool"):
        JoinedSessionCapabilities(detach_safe=1)  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        JoinedSessionCapabilities().detach_safe = True  # type: ignore[misc]


def test_qualified_surface_parses_claims() -> None:
    declaration = _build(_joinable_surface(joined_capabilities={"detach_safe": True, "prompt_delivery": True}))
    assert declaration.joined_capabilities.detach_safe is True
    assert declaration.joined_capabilities.prompt_delivery is True
    assert declaration.joined_capabilities.human_concurrency_safe is False


@pytest.mark.parametrize(
    ("joined", "fragment"),
    [
        ({"detach_safe": "yes"}, "must be booleans"),
        ({"detach_safe": 1}, "must be booleans"),
        ({"steer": True}, "unknown joined_capabilities fields"),
        (["detach_safe"], "must be a mapping"),
    ],
)
def test_loader_rejects_loose_values(joined, fragment) -> None:
    with pytest.raises(AudiaGenticError, match=fragment) as raised:
        _build(_joinable_surface(joined_capabilities=joined))
    assert raised.value.code == "VAL-PCAP-011"


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"identity_operations": {"open": "supported", "attach-existing": "unsupported"}}, "attach-existing"),
        ({"ownership_modes": ["owned"]}, "external-ownership"),
        ({"mapping_facts": None}, "exact-session-mapping"),
        ({"evidence": {"validated": False}, "controls": {}, "platforms": []}, "validated-evidence"),
    ],
)
def test_claims_require_join_prerequisites(overrides, missing) -> None:
    with pytest.raises(AudiaGenticError, match="joined capabilities require") as raised:
        _build(_joinable_surface(joined_capabilities=ALL_CLAIMS, **overrides))
    assert missing in raised.value.details["missing"]


def test_no_shipped_provider_claims_a_join() -> None:
    from audiagentic.components.providers.descriptors.loader import (
        get_providers_config_dir,
        load_providers_from_directory,
    )

    for descriptor in load_providers_from_directory(get_providers_config_dir()).values():
        for surface in descriptor.session_surfaces:
            assert not surface.joined_capabilities.claimed, (descriptor.provider_id, surface.surface_id)


def _register_joinable(tmp_path: Path, provider_id: str, *, validated: bool) -> None:
    from audiagentic.components.providers.descriptors.session_surface_declarations import (
        SessionSurfaceDeclaration,
    )

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
    _register_joinable(tmp_path, "join-provider", validated=True)
    resolved = resolve_session_surface(tmp_path, "join-provider", SurfaceHint(surface_id="acp"))
    assert resolved.validation.outcome is SurfaceResolutionOutcome.SUPPORTED
    assert resolved.joined == JoinedSessionCapabilities(detach_safe=True)


def test_unvalidated_claims_never_reach_the_projection(tmp_path: Path) -> None:
    # The declaration type alone does not run rule 6; the projection still drops
    # claims whose evidence is not validated.
    _register_joinable(tmp_path, "unproven-provider", validated=False)
    resolved = resolve_session_surface(tmp_path, "unproven-provider", SurfaceHint(surface_id="acp"))
    assert resolved.validation.outcome is SurfaceResolutionOutcome.UNPROVEN
    assert not resolved.joined.claimed
