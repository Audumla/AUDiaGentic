"""SH39: the shipped OpenCode surface claims only what was measured, bound to queue delivery, and never joins on partial evidence."""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

from audiagentic.components.providers.adapters.opencode import join as opencode_join
from audiagentic.components.providers.descriptors import all_descriptors
from audiagentic.components.providers.services.qualification import evidence
from audiagentic.components.providers.services.session import join_readiness
from audiagentic.components.providers.services.session.join_readiness import resolve_join_readiness
from audiagentic.foundation.transports.session_surface import (
    ControlSupport,
    SessionIdentityOperation,
    SessionOwnershipMode,
    SurfaceResolutionOutcome,
)

ADAPTER_REF = "audiagentic.components.providers.adapters.opencode.join:OpenCodeClient"
EXE = "sha256:" + "a" * 64
FACTS = {"platform": "linux-amd64", "executable-version": "2.2.5", "executable-digest": EXE}


def _surface():
    return next(s for s in all_descriptors()["opencode"].session_surfaces if s.surface_id == "opencode-app")


def test_the_surface_is_an_external_attach_surface_and_the_owned_surfaces_are_untouched() -> None:
    surface = _surface()
    assert surface.identity_operations[SessionIdentityOperation.ATTACH_EXISTING] is ControlSupport.SUPPORTED
    assert surface.ownership_modes == (SessionOwnershipMode.EXTERNAL,) and surface.adapter_ref == ADAPTER_REF
    for other in all_descriptors()["opencode"].session_surfaces:
        if other.surface_id != "opencode-app":
            assert other.ownership_modes == (SessionOwnershipMode.OWNED,) and not other.joined_capabilities.claimed


def test_it_claims_what_was_measured_and_never_result_correlation() -> None:
    claims = _surface().joined_capabilities
    assert claims.detach_safe and claims.prompt_delivery and claims.native_atomic_queue_admission
    assert claims.human_concurrency_safe
    # Assistant messages carry no native link to their prompt (unsupported-result-not-linked-by-native-id).
    assert claims.correlated_terminal_output is False and not claims.qualified


def test_the_admission_claim_is_bound_to_queue_delivery_in_the_adapter() -> None:
    """The evidence was measured for delivery="queue"; the server default is "steer", which must be unreachable."""
    assert opencode_join.QUEUE_DELIVERY == "queue"
    assert "delivery" not in inspect.signature(opencode_join.OpenCodeClient.prompt).parameters
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(opencode_join.OpenCodeClient.prompt)))
    # Every "delivery" key written into the request body must come from the QUEUE_DELIVERY constant.
    values = [value for node in ast.walk(tree) if isinstance(node, ast.Dict)
              for key, value in zip(node.keys, node.values, strict=True)
              if isinstance(key, ast.Constant) and key.value == "delivery"]
    assert values and all(isinstance(v, ast.Name) and v.id == "QUEUE_DELIVERY" for v in values)


def _record(adapter, state_root: Path, *, correlated: bool = False) -> None:
    caps = {"passive-identity": True, "existing-session-attach": True, "safe-detach": True, "reconnect": True,
            "concurrent-human-use": True, "conditional-admission": True, "correlated-result": correlated}
    record = evidence.build_record(
        producer={"component": "providers", "qualifier-version": "1", "suite-digest": "sha256:" + "5" * 64,
                  "adapter-id": adapter.adapter_id, "adapter-version": "1", "adapter-digest": adapter.adapter_digest},
        target={"provider-id": "opencode", "surface-id": "opencode-app", "platform": "linux-amd64",
                "executable-version": "2.2.5", "executable-digest": EXE, "native-protocol": "opencode-http-v2",
                "native-schema-version": adapter.native_schema_version, "endpoint-kind": "http"},
        qualification={"state": "supported" if correlated else "partial", "capabilities": caps,
                       "unsupported-reasons": [] if correlated else ["unsupported-result-not-linked-by-native-id"]},
        proof={"fixture-id": "disposable-opencode", "test-run-id": "run-1", "artifact-digest": "sha256:" + "f" * 64,
               "verified-at": "2026-11-01T00:00:00Z"},
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    evidence.write_evidence(record, state_root=state_root)


def test_without_an_exact_record_the_surface_is_unproven(tmp_path: Path) -> None:
    adapter = join_readiness.adapter_identity(ADAPTER_REF)
    readiness = resolve_join_readiness("opencode", "opencode-app", facts=FACTS, adapter=adapter, state_root=tmp_path)
    assert readiness.outcome is SurfaceResolutionOutcome.UNPROVEN and readiness.reasons == ("no-exact-evidence",)


def test_the_measured_six_of_seven_record_is_unsupported_for_exactly_one_reason(tmp_path: Path) -> None:
    adapter = join_readiness.adapter_identity(ADAPTER_REF)
    _record(adapter, tmp_path)
    readiness = resolve_join_readiness("opencode", "opencode-app", facts=FACTS, adapter=adapter, state_root=tmp_path)
    assert not readiness.ready and readiness.outcome is SurfaceResolutionOutcome.UNSUPPORTED
    assert readiness.reasons == ("unproven-correlated_terminal_output",)


def test_another_executable_or_an_older_version_never_reuses_the_record(tmp_path: Path) -> None:
    adapter = join_readiness.adapter_identity(ADAPTER_REF)
    _record(adapter, tmp_path)
    other = {**FACTS, "executable-digest": "sha256:" + "d" * 64}
    assert resolve_join_readiness("opencode", "opencode-app", facts=other, adapter=adapter,
                                  state_root=tmp_path).reasons == ("no-exact-evidence",)
    older = {**FACTS, "executable-version": "1.9.0"}
    assert resolve_join_readiness("opencode", "opencode-app", facts=older, adapter=adapter,
                                  state_root=tmp_path).reasons == ("version-not-declared",)


def test_the_shipped_matrix_routes_nothing_for_opencode(tmp_path: Path) -> None:
    from audiagentic.components.providers.services.session.join_authority import join_matrix

    rows = [row for row in join_matrix(state_root=tmp_path, facts={"opencode": FACTS}) if row.provider_id == "opencode"]
    assert any(row.surface_id == "opencode-app" for row in rows)
    assert all(row.outcome is not SurfaceResolutionOutcome.SUPPORTED for row in rows)
