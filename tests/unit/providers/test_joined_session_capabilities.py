"""SH39 claims-only slice: strict source loading, contradiction checks and projection."""
from dataclasses import FrozenInstanceError, fields

import pytest
import yaml

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.descriptors.loader import (
    PROVIDER_SPEC,
    get_providers_config_dir,
    load_provider_descriptor,
    load_providers_from_directory,
)
from audiagentic.components.providers.descriptors.session_surface_declarations import (
    SessionSurfaceDeclaration,
    validate_session_surface_declarations,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    JoinedSessionCapabilities,
    ResolvedSessionSurface,
    SessionControlAction,
    SessionIdentityCapabilities,
    SessionSurfaceRef,
)

FLAGS = tuple(field.name for field in fields(JoinedSessionCapabilities))
ALL_CLAIMS = dict.fromkeys(FLAGS, True)


def descriptor_data(surface):
    return {"provider_id": "joined-fixture", "display_name": "Fixture",
            "execution_isolation_tier": "no-isolation", "session_surfaces": [surface]}


def surface_data():
    return {
        "surface_id": "native-existing", "version_constraint": ">=1.0",
        "identity_operations": {"attach-existing": "supported"},
        "ownership_modes": ["external"],
        "mapping_facts": {
            "ref_scope": "surface", "ref_namespace": "provider-session-ref",
            "requires_same_project": True, "requires_same_execution_context": True,
            "share_existing": True, "concurrent_attachments": True, "replace_existing": False,
        },
        "evidence": {"validated": True, "reference": "synthetic-declaration-fixture"},
        "platforms": [{"platform": "windows-amd64", "evidence": {
            "validated": True, "reference": "synthetic-platform-fixture",
        }}],
        "joined_capabilities": dict(ALL_CLAIMS),
    }


def build(surface):
    return PROVIDER_SPEC.build(descriptor_data(surface))


def test_neutral_claims_are_frozen_strict_and_default_unsupported():
    default = JoinedSessionCapabilities()
    assert not default.qualified and all(getattr(default, key) is False for key in FLAGS)
    with pytest.raises(FrozenInstanceError):
        default.detach_safe = True
    assert JoinedSessionCapabilities(**ALL_CLAIMS).qualified
    for missing in FLAGS:
        assert not JoinedSessionCapabilities(**{**ALL_CLAIMS, missing: False}).qualified
    resolved = ResolvedSessionSurface(SessionSurfaceRef("p", "s", "1"), SessionIdentityCapabilities())
    assert resolved.joined_capabilities == default


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("value", [0, 1, "true", "false", None, [], {}, 1.0])
def test_neutral_and_yaml_claims_reject_boolean_coercion(flag, value):
    with pytest.raises(ValueError, match="boolean"):
        JoinedSessionCapabilities(**{flag: value})
    surface = surface_data()
    surface["joined_capabilities"][flag] = value
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
        build(surface)


@pytest.mark.parametrize("value", [None, False, [], "unsupported", {"qualified": True}, {"extra": False}, {1: True}])
def test_loader_rejects_untyped_container_and_unknown_keys(value):
    surface = surface_data()
    surface["joined_capabilities"] = value
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
        build(surface)


@pytest.mark.parametrize("key,value", [
    ("identity_operations", {"attach-existing": "unsupported"}),
    ("ownership_modes", ["owned"]), ("mapping_facts", {}),
    ("evidence", {"validated": False, "reference": "fixture"}),
    ("platforms", []),
    ("platforms", [{"platform": "windows-amd64", "evidence": {"validated": False}}]),
    ("platforms", [{"platform": "", "evidence": {"validated": True, "reference": "fixture"}}]),
])
def test_qualified_join_contradictions_are_rejected(key, value):
    surface = surface_data()
    surface[key] = value
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
        build(surface)


@pytest.mark.parametrize("key,value", [
    ("ref_scope", "unknown"), ("ref_namespace", ""),
    ("requires_same_project", False), ("requires_same_execution_context", False),
    ("share_existing", False), ("concurrent_attachments", False), ("replace_existing", True),
    ("share_existing", "true"), ("concurrent_attachments", 1), ("attach_while_turn_active", "false"),
])
def test_qualified_join_requires_explicit_exact_shared_mapping(key, value):
    surface = surface_data()
    surface["mapping_facts"][key] = value
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
        build(surface)


@pytest.mark.parametrize("where", ["parent", "platform"])
@pytest.mark.parametrize("value", ["false", "true", 1])
def test_qualified_evidence_cannot_use_ordinary_truthiness_coercion(where, value):
    surface = surface_data()
    evidence = surface["evidence"] if where == "parent" else surface["platforms"][0]["evidence"]
    evidence["validated"] = value
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
        build(surface)


def test_direct_declaration_validation_rejects_untyped_claims():
    declaration = SessionSurfaceDeclaration("s", ">=1", joined_capabilities={})
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
        validate_session_surface_declarations((declaration,))
    with pytest.raises(ValueError):
        ResolvedSessionSurface(
            SessionSurfaceRef("p", "s", "1"), SessionIdentityCapabilities(), joined_capabilities={},
        )


@pytest.mark.parametrize("claims", [{}, {"detach_safe": True}, ALL_CLAIMS])
def test_actual_yaml_loader_and_public_resolution_project_same_claims(tmp_path, monkeypatch, claims):
    from audiagentic.components.providers.descriptors.registry import _registry, register
    from audiagentic.components.providers.services.config.provider_config import (
        set_provider_enabled,
    )

    surface = surface_data()
    surface["joined_capabilities"] = claims
    path = tmp_path / "fixture.yaml"
    path.write_text(yaml.safe_dump(descriptor_data(surface)), encoding="utf-8")
    declaration = load_provider_descriptor(path)
    monkeypatch.setattr(_registry, "_items", {})
    monkeypatch.setattr(_registry, "_loaded", True)
    register(declaration)
    set_provider_enabled(tmp_path, declaration.provider_id, enabled=True)
    result = providers_api.resolve_session_surface(
        tmp_path, declaration.provider_id,
        SurfaceHint("native-existing", platform_hint="windows-amd64"),
    )
    expected = declaration.session_surfaces[0].joined_capabilities
    assert result.joined_capabilities is expected
    assert result.joined_capabilities == JoinedSessionCapabilities(**claims)
    assert not result.control_supported(SessionControlAction.STEER_TURN)
    # This asserts declaration projection only, not strict/live readiness.


def test_existing_owned_acp_and_generic_factory_do_not_imply_join_claims():
    providers = load_providers_from_directory(get_providers_config_dir())
    for descriptor in providers.values():
        for declaration in descriptor.session_surfaces:
            assert not declaration.joined_capabilities.qualified
    ordinary = {"surface_id": "acp", "version_constraint": ">=1",
                "ownership_modes": ["owned"],
                "adapter_ref": "audiagentic.foundation.transports.session_surface:ControlSupport"}
    assert not build(ordinary).session_surfaces[0].joined_capabilities.qualified
    ordinary["joined_capabilities"] = {"detach_safe": True}
    assert not build(ordinary).session_surfaces[0].joined_capabilities.qualified
