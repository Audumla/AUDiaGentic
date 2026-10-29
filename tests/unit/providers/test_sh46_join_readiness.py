"""SH46: strict joined-session readiness refuses every unknown and needs exact proof."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from tests.unit.providers.test_session_surface_resolution import (  # noqa: F401 - autouse fixture
    _fake_descriptor,
    _isolate_registry,
)

from audiagentic.components.providers.descriptors.registry import register
from audiagentic.components.providers.descriptors.session_surface_declarations import SessionSurfaceDeclaration
from audiagentic.components.providers.services.qualification import evidence
from audiagentic.components.providers.services.session import join_readiness
from audiagentic.components.providers.services.session.join_readiness import (
    AdapterIdentity,
    JoinAdapterInfo,
    resolve_join_readiness,
)
from audiagentic.foundation.transports.session_surface import (
    ControlSupport,
    JoinedSessionCapabilities,
    PlatformEvidence,
    SessionIdentityOperation,
    SessionMappingFacts,
    SessionOwnershipMode,
    SurfaceResolutionOutcome,
    ValidationEvidence,
)

JOIN_ADAPTER = JoinAdapterInfo("fake-join", "1", "7")
EXE = "sha256:" + "e" * 64
ADAPTER = AdapterIdentity("fake-join", "sha256:" + "a" * 64, "7")
PLATFORM = "linux-amd64"
FACTS = {"platform": PLATFORM, "executable-version": "2.3.0", "executable-digest": EXE}
ALL_CLAIMS = JoinedSessionCapabilities(True, True, True, True, True)
ALL_PROVEN = {"passive-identity": True, "existing-session-attach": True, "conditional-admission": True,
              "correlated-result": True, "safe-detach": True, "concurrent-human-use": True}


def fake_factory():  # adapter_ref target; JOIN_ADAPTER above marks this module as a join adapter
    return None


def _declaration(**changes) -> SessionSurfaceDeclaration:
    validated = ValidationEvidence(validated=True, reference="tests/fixtures/join.md")
    values = dict(
        surface_id="app-server", version_constraint=">=2.0", evidence=validated,
        identity_operations={SessionIdentityOperation.ATTACH_EXISTING: ControlSupport.SUPPORTED},
        ownership_modes=(SessionOwnershipMode.EXTERNAL,),
        mapping_facts=SessionMappingFacts(ref_scope="provider-session"),
        platforms=(PlatformEvidence(PLATFORM, validated),), joined_capabilities=ALL_CLAIMS,
        adapter_ref="tests.unit.providers.test_sh46_join_readiness:fake_factory",
    )
    values.update(changes)
    return SessionSurfaceDeclaration(**values)


def _register(*declarations: SessionSurfaceDeclaration) -> None:
    register(_fake_descriptor("joiner", session_surfaces=declarations or (_declaration(),)))


def _evidence(state_root: Path, *, capabilities=None, version="2.3.0", adapter=ADAPTER, state="supported") -> str:
    record = evidence.build_record(
        producer={"component": "providers", "qualifier-version": "1", "suite-digest": "sha256:" + "5" * 64,
                  "adapter-id": adapter.adapter_id, "adapter-version": "1", "adapter-digest": adapter.adapter_digest},
        target={"provider-id": "joiner", "surface-id": "app-server", "platform": PLATFORM,
                "executable-version": version, "executable-digest": EXE, "native-protocol": "json-rpc",
                "native-schema-version": adapter.native_schema_version, "endpoint-kind": "socket"},
        qualification={"state": state, "capabilities": ALL_PROVEN if capabilities is None else capabilities,
                       "unsupported-reasons": []},
        proof={"fixture-id": "disposable-joiner", "test-run-id": "run-1", "artifact-digest": "sha256:" + "f" * 64,
               "verified-at": "2026-10-29T00:00:00Z"},
        created_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
    )
    evidence.write_evidence(record, state_root=state_root)
    return record["evidence-id"]


def _resolve(tmp_path: Path, *, facts=None, adapter=ADAPTER):
    return resolve_join_readiness("joiner", "app-server", facts=FACTS if facts is None else facts,
                                  adapter=adapter, state_root=tmp_path)


def test_exact_evidence_makes_a_declared_join_ready(tmp_path: Path) -> None:
    _register()
    evidence_id = _evidence(tmp_path)
    readiness = _resolve(tmp_path)
    assert readiness.ready and readiness.reasons == ()
    assert readiness.evidence_id == evidence_id
    assert readiness.proven == ALL_CLAIMS


@pytest.mark.parametrize(
    ("facts", "outcome", "reason"),
    [
        ({**FACTS, "executable-digest": None}, SurfaceResolutionOutcome.UNAVAILABLE, "executable-not-found"),
        ({**FACTS, "executable-version": None}, SurfaceResolutionOutcome.UNPROVEN, "installed-version-unknown"),
        ({**FACTS, "executable-version": "codex-cli 2.3.0"}, SurfaceResolutionOutcome.UNPROVEN,
         "installed-version-unknown"),
        ({**FACTS, "executable-version": "1.9.0"}, SurfaceResolutionOutcome.UNSUPPORTED, "version-not-declared"),
        ({**FACTS, "platform": "windows-amd64"}, SurfaceResolutionOutcome.UNSUPPORTED, "platform-not-validated"),
        ({**FACTS, "executable-digest": "sha256:" + "0" * 64}, SurfaceResolutionOutcome.UNPROVEN,
         "no-exact-evidence"),
    ],
)
def test_installed_facts_must_match_exactly(tmp_path: Path, facts, outcome, reason) -> None:
    _register()
    _evidence(tmp_path)
    readiness = _resolve(tmp_path, facts=facts)
    assert (readiness.outcome, readiness.reasons) == (outcome, (reason,))


def test_declaration_gaps_refuse(tmp_path: Path) -> None:
    _evidence(tmp_path)
    _register(_declaration(joined_capabilities=JoinedSessionCapabilities()))
    assert _resolve(tmp_path).reasons == ("join-not-declared",)
    _register(_declaration(version_constraint="~2"))
    assert _resolve(tmp_path).reasons == ("unparseable-version-constraint",)
    _register(_declaration(), _declaration(version_constraint=">=2.1"))
    assert _resolve(tmp_path).reasons == ("ambiguous-version-declarations",)
    assert resolve_join_readiness("nobody", "app-server", facts=FACTS, state_root=tmp_path).reasons == (
        "unknown-provider",)


def test_adapter_must_declare_itself_and_match_the_evidence(tmp_path: Path) -> None:
    implemented = join_readiness.adapter_identity(f"{__name__}:fake_factory")
    assert implemented is not None and implemented.native_schema_version == "7"
    assert implemented.adapter_digest == evidence.file_digest(Path(__file__))
    assert join_readiness.adapter_identity("audiagentic.foundation.config.refs:resolve_ref") is None  # callable only
    assert join_readiness.adapter_identity("no.such.module:factory") is None
    _register(_declaration(adapter_ref="audiagentic.foundation.config.refs:resolve_ref"))
    assert resolve_join_readiness("joiner", "app-server", facts=FACTS, state_root=tmp_path).reasons == (
        "adapter-not-implemented",)
    _evidence(tmp_path)  # evidence for a different adapter digest than the real module's
    _register()
    assert resolve_join_readiness("joiner", "app-server", facts=FACTS, state_root=tmp_path).reasons == (
        "no-exact-evidence",)


def test_evidence_must_prove_the_claims(tmp_path: Path) -> None:
    _register()
    _evidence(tmp_path, capabilities={**ALL_PROVEN, "existing-session-attach": False})
    assert _resolve(tmp_path).reasons == ("unproven-existing-session-attach",)


def test_mandatory_capabilities(tmp_path: Path) -> None:
    _register()
    _evidence(tmp_path, capabilities={**ALL_PROVEN, "safe-detach": False, "concurrent-human-use": False,
                                      "conditional-admission": False})
    readiness = _resolve(tmp_path)
    assert readiness.outcome is SurfaceResolutionOutcome.UNSUPPORTED
    assert readiness.reasons == ("unproven-detach_safe", "unproven-prompt_delivery",
                                 "unproven-concurrency-safe-admission")
    assert readiness.proven == JoinedSessionCapabilities(correlated_terminal_output=True)


def test_native_queue_alone_satisfies_concurrency(tmp_path: Path) -> None:
    _register(_declaration(joined_capabilities=JoinedSessionCapabilities(
        detach_safe=True, prompt_delivery=True, native_atomic_queue_admission=True, correlated_terminal_output=True)))
    _evidence(tmp_path, capabilities={**ALL_PROVEN, "concurrent-human-use": False})
    assert _resolve(tmp_path).ready


def test_undeclared_claims_are_not_borrowed_from_evidence(tmp_path: Path) -> None:
    _register(_declaration(joined_capabilities=JoinedSessionCapabilities(detach_safe=True)))
    _evidence(tmp_path)
    readiness = _resolve(tmp_path)
    assert readiness.proven == JoinedSessionCapabilities(detach_safe=True)
    assert not readiness.ready


@pytest.mark.parametrize(("state", "version"), [("unsupported", "2.3.0"), ("supported", "2.2.0")])
def test_negative_or_stale_evidence_refuses(tmp_path: Path, state, version) -> None:
    _register()
    _evidence(tmp_path, state=state, version=version)
    assert not _resolve(tmp_path).ready


def test_shipped_providers_are_never_ready(tmp_path: Path) -> None:
    from audiagentic.components.providers.descriptors.loader import (
        get_providers_config_dir,
        load_providers_from_directory,
    )

    for descriptor in load_providers_from_directory(get_providers_config_dir()).values():
        register(descriptor)
        for surface in descriptor.session_surfaces:
            readiness = resolve_join_readiness(descriptor.provider_id, surface.surface_id, facts=FACTS,
                                               state_root=tmp_path)
            assert not readiness.ready, (descriptor.provider_id, surface.surface_id)
