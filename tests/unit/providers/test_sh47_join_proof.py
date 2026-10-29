"""SH47: passive proof that the live instance is the qualified one."""
from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.providers.test_sh46_join_readiness import (  # noqa: F401 - autouse fixture
    ADAPTER,
    EXE,
    FACTS,
    _evidence,
    _isolate_registry,
    _register,
)

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.services.session.join_proof import (
    InstanceObservation,
    InstanceQuery,
    inspect_join_instance,
)
from audiagentic.components.providers.services.session.join_readiness import (
    AdapterIdentity,
    resolve_join_readiness,
)
from audiagentic.foundation.transports.session_surface import SurfaceResolutionOutcome

GOOD = InstanceObservation(alive=True, executable_digest=EXE, executable_version="2.3.0",
                           native_schema_version="7", endpoint_kind="socket", session_ref="s1", generation="g1")


class Inspector:
    def __init__(self, observation=GOOD, error: Exception | None = None) -> None:
        self.observation, self.error, self.queries = observation, error, []

    def __call__(self, query: InstanceQuery):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.observation


def _ready(tmp_path: Path, inspector):
    _register()
    _evidence(tmp_path)
    adapter = AdapterIdentity(ADAPTER.adapter_id, ADAPTER.adapter_digest, ADAPTER.native_schema_version, inspector)
    return resolve_join_readiness("joiner", "app-server", facts=FACTS, adapter=adapter, state_root=tmp_path)


def _inspect(tmp_path: Path, inspector, **kwargs):
    return inspect_join_instance("joiner", "app-server", endpoint="/run/app.sock", session_ref="s1",
                                 readiness=_ready(tmp_path, inspector), **kwargs)


def test_matching_instance_is_proven_with_its_generation(tmp_path: Path) -> None:
    inspector = Inspector()
    proof = _inspect(tmp_path, inspector, expected_generation="g1")
    assert proof.proven and proof.reasons == ()
    assert (proof.generation, proof.session_ref) == ("g1", "s1")
    assert proof.evidence_id is not None
    assert inspector.queries == [InstanceQuery("joiner", "app-server", "/run/app.sock", "s1")]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"executable_digest": "sha256:" + "0" * 64}, "executable-digest-mismatch"),  # PATH binary, not the server
        ({"executable_version": "2.2.0"}, "executable-version-mismatch"),
        ({"native_schema_version": "8"}, "schema-version-mismatch"),
        ({"endpoint_kind": "http"}, "endpoint-kind-mismatch"),
        ({"session_ref": "other"}, "session-mismatch"),
    ],
)
def test_any_identity_difference_refuses(tmp_path: Path, changes, reason) -> None:
    proof = _inspect(tmp_path, Inspector(replace(GOOD, **changes)))
    assert not proof.proven and proof.outcome is SurfaceResolutionOutcome.UNPROVEN
    assert proof.reasons == (reason,)
    assert proof.generation is None


def test_replaced_instance_is_refused_by_generation(tmp_path: Path) -> None:
    proof = _inspect(tmp_path, Inspector(replace(GOOD, generation="g2")), expected_generation="g1")
    assert proof.reasons == ("generation-changed",) and not proof.proven


@pytest.mark.parametrize(
    ("inspector", "outcome", "reason"),
    [
        (Inspector(error=OSError("socket gone")), SurfaceResolutionOutcome.UNAVAILABLE, "inspection-failed"),
        (Inspector(replace(GOOD, alive=False)), SurfaceResolutionOutcome.UNAVAILABLE, "instance-not-alive"),
        (Inspector(replace(GOOD, generation="")), SurfaceResolutionOutcome.UNPROVEN, "malformed-observation"),
        (Inspector("not an observation"), SurfaceResolutionOutcome.UNPROVEN, "malformed-observation"),
        (None, SurfaceResolutionOutcome.UNSUPPORTED, "adapter-cannot-inspect"),
    ],
)
def test_inspection_gaps_refuse(tmp_path: Path, inspector, outcome, reason) -> None:
    proof = _inspect(tmp_path, inspector)
    assert (proof.outcome, proof.reasons) == (outcome, (reason,))


def test_requires_static_readiness_first(tmp_path: Path) -> None:
    inspector = Inspector()
    _register()  # no evidence recorded
    readiness = resolve_join_readiness(
        "joiner", "app-server", facts=FACTS, state_root=tmp_path,
        adapter=AdapterIdentity(ADAPTER.adapter_id, ADAPTER.adapter_digest, "7", inspector))
    proof = inspect_join_instance("joiner", "app-server", endpoint="e", session_ref="s1", readiness=readiness)
    assert proof.reasons == ("not-join-ready", "no-exact-evidence")
    assert inspector.queries == []  # never reaches the live instance


def test_endpoint_and_session_are_required(tmp_path: Path) -> None:
    for endpoint, session in (("", "s1"), ("e", "")):
        proof = inspect_join_instance("joiner", "app-server", endpoint=endpoint, session_ref=session)
        assert proof.reasons == ("endpoint-and-session-required",)


def test_inspection_starts_no_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    readiness = _ready(tmp_path, Inspector())

    def forbidden(*args, **kwargs):
        raise AssertionError("passive proof must not start a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert inspect_join_instance("joiner", "app-server", endpoint="e", session_ref="s1", readiness=readiness).proven


def test_public_boundary_refuses_shipped_providers(tmp_path: Path) -> None:
    proof = providers_api.inspect_join_instance("pi", "pi-acp", endpoint="e", session_ref="s1", state_root=tmp_path)
    assert not proof.proven and proof.reasons[0] == "not-join-ready"
