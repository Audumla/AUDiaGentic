"""SH48: one Provider authority for the join matrix, registration and revalidation."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tests.unit.providers.test_sh46_join_readiness import (  # noqa: F401 - autouse fixture
    ADAPTER,
    FACTS,
    _declaration,
    _fake_descriptor,
    _evidence,
    _isolate_registry,
    _register,
)
from tests.unit.providers.test_sh47_join_proof import GOOD, Inspector

from audiagentic.components.providers.descriptors.registry import register
from audiagentic.components.providers.services.session.join_authority import (
    join_matrix,
    register_join,
    revalidate_join,
)
from audiagentic.components.providers.services.session.join_readiness import AdapterIdentity
from audiagentic.foundation.transports.session_surface import (
    JoinedSessionCapabilities,
    SurfaceResolutionOutcome,
)

SUPPORTED = SurfaceResolutionOutcome.SUPPORTED


def _adapter(inspector) -> AdapterIdentity:
    return AdapterIdentity(ADAPTER.adapter_id, ADAPTER.adapter_digest, ADAPTER.native_schema_version, inspector)


def _registered(tmp_path: Path, inspector=None):
    _register()
    _evidence(tmp_path)
    decision = register_join("joiner", "app-server", endpoint="/run/app.sock", session_ref="s1",
                             state_root=tmp_path, facts=FACTS, adapter=_adapter(inspector or Inspector()))
    return decision


def test_registration_carries_exactly_what_was_proven(tmp_path: Path) -> None:
    decision = _registered(tmp_path)
    assert decision.routable and decision.reasons == ()
    registration = decision.registration
    assert (registration.provider_id, registration.surface_id, registration.endpoint) == (
        "joiner", "app-server", "/run/app.sock")
    assert (registration.session_ref, registration.generation, registration.executable_version) == ("s1", "g1", "2.3.0")
    assert registration.evidence_id.startswith("qe_") and registration.executable_digest == FACTS["executable-digest"]


def test_no_registration_without_readiness_or_proof(tmp_path: Path) -> None:
    _register()  # no evidence
    decision = register_join("joiner", "app-server", endpoint="e", session_ref="s1", state_root=tmp_path,
                             facts=FACTS, adapter=_adapter(Inspector()))
    assert not decision.routable and decision.registration is None
    assert decision.reasons == ("not-join-ready", "no-exact-evidence")

    _evidence(tmp_path)
    refused = register_join("joiner", "app-server", endpoint="e", session_ref="s1", state_root=tmp_path,
                            facts=FACTS, adapter=_adapter(Inspector(replace(GOOD, executable_digest="sha256:" + "0" * 64))))
    assert not refused.routable and refused.registration is None
    assert refused.reasons == ("executable-digest-mismatch",)


def test_revalidation_passes_while_nothing_changed(tmp_path: Path) -> None:
    registration = _registered(tmp_path).registration
    again = revalidate_join(registration, state_root=tmp_path, facts=FACTS, adapter=_adapter(Inspector()))
    assert again.routable and again.registration == registration


def test_replaced_instance_is_not_routable(tmp_path: Path) -> None:
    registration = _registered(tmp_path).registration
    decision = revalidate_join(registration, state_root=tmp_path, facts=FACTS,
                               adapter=_adapter(Inspector(replace(GOOD, generation="g2"))))
    assert not decision.routable and decision.reasons == ("generation-changed",)


def test_instance_that_went_away_is_not_routable(tmp_path: Path) -> None:
    registration = _registered(tmp_path).registration
    decision = revalidate_join(registration, state_root=tmp_path, facts=FACTS,
                               adapter=_adapter(Inspector(error=OSError("socket gone"))))
    assert not decision.routable and decision.reasons == ("inspection-failed",)


def test_changed_evidence_or_executable_revokes(tmp_path: Path) -> None:
    registration = _registered(tmp_path).registration
    for changes, reason in (({"evidence_id": "qe_" + "0" * 24}, "evidence-changed"),
                            ({"executable_digest": "sha256:" + "0" * 64}, "executable-changed")):
        decision = revalidate_join(replace(registration, **changes), state_root=tmp_path, facts=FACTS,
                                   adapter=_adapter(Inspector()))
        assert decision.reasons == (reason,) and not decision.routable


def test_lost_evidence_revokes_routability(tmp_path: Path) -> None:
    registration = _registered(tmp_path).registration
    for record in (tmp_path / "providers" / "qualification" / "v1" / "joiner").glob("qe_*.json"):
        record.unlink()
    decision = revalidate_join(registration, state_root=tmp_path, facts=FACTS, adapter=_adapter(Inspector()))
    assert not decision.routable and decision.reasons == ("not-join-ready", "no-exact-evidence")


def test_matrix_comes_from_the_same_resolver(tmp_path: Path) -> None:
    register(_fake_descriptor(
        "joiner", session_surfaces=(
            _declaration(),
            _declaration(surface_id="plain", version_constraint=">=1.0",
                         joined_capabilities=JoinedSessionCapabilities(), adapter_ref=None),
        )))
    _evidence(tmp_path)
    rows = join_matrix(state_root=tmp_path, facts={"joiner": FACTS},
                       adapters={("joiner", "app-server"): _adapter(Inspector())})
    by_surface = {row.surface_id: row for row in rows}
    assert by_surface["app-server"].outcome is SUPPORTED and by_surface["app-server"].reasons == ()
    assert by_surface["plain"].outcome is SurfaceResolutionOutcome.UNSUPPORTED
    assert by_surface["plain"].reasons == ("join-not-declared",)


def test_no_shipped_provider_is_routable(tmp_path: Path) -> None:
    from audiagentic.components.providers.descriptors.loader import (
        get_providers_config_dir,
        load_providers_from_directory,
    )

    providers = load_providers_from_directory(get_providers_config_dir())
    for descriptor in providers.values():
        register(descriptor)
    rows = join_matrix(state_root=tmp_path, facts={provider_id: FACTS for provider_id in providers})
    assert rows and not any(row.outcome is SUPPORTED for row in rows)
