"""SH39: the shipped Codex app-server surface claims only what is proven and is never joinable without exact evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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

ADAPTER_REF = "audiagentic.components.providers.adapters.codex.join:AppServerClient"
EXE = "sha256:" + "c" * 64
FACTS = {"platform": "linux-amd64", "executable-version": "0.166.0", "executable-digest": EXE}


def _surface():
    return next(s for s in all_descriptors()["codex"].session_surfaces if s.surface_id == "codex-app-server")


def test_the_declaration_is_an_external_attach_surface_and_leaves_the_owned_acp_surface_alone() -> None:
    surface = _surface()
    assert surface.identity_operations[SessionIdentityOperation.ATTACH_EXISTING] is ControlSupport.SUPPORTED
    assert surface.ownership_modes == (SessionOwnershipMode.EXTERNAL,)
    assert surface.adapter_ref == ADAPTER_REF
    acp = next(s for s in all_descriptors()["codex"].session_surfaces if s.surface_id == "codex-acp")
    assert acp.ownership_modes == (SessionOwnershipMode.OWNED,) and not acp.joined_capabilities.claimed


def test_it_claims_only_what_the_live_probes_proved() -> None:
    claims = _surface().joined_capabilities
    assert claims.detach_safe is True and claims.human_concurrency_safe is True
    # Measured on codex 0.166.0 (SH54-C): turn/start while a turn is active steers it, so these are never claimed.
    assert not (claims.prompt_delivery or claims.native_atomic_queue_admission or claims.correlated_terminal_output)
    assert not claims.qualified


def test_without_an_exact_record_the_surface_is_unproven(tmp_path: Path) -> None:
    adapter = join_readiness.adapter_identity(ADAPTER_REF)
    readiness = resolve_join_readiness("codex", "codex-app-server", facts=FACTS, adapter=adapter, state_root=tmp_path)
    assert readiness.outcome is SurfaceResolutionOutcome.UNPROVEN and readiness.reasons == ("no-exact-evidence",)


def _partial_record(adapter, state_root: Path) -> None:
    caps = {"passive-identity": True, "existing-session-attach": True, "safe-detach": True, "reconnect": True,
            "concurrent-human-use": True, "conditional-admission": False, "correlated-result": False}
    record = evidence.build_record(
        producer={"component": "providers", "qualifier-version": "1", "suite-digest": "sha256:" + "5" * 64,
                  "adapter-id": adapter.adapter_id, "adapter-version": "1", "adapter-digest": adapter.adapter_digest},
        target={"provider-id": "codex", "surface-id": "codex-app-server", "platform": "linux-amd64",
                "executable-version": "0.166.0", "executable-digest": EXE, "native-protocol": "codex-app-server-jsonrpc-ws",
                "native-schema-version": adapter.native_schema_version, "endpoint-kind": "socket"},
        qualification={"state": "partial", "capabilities": caps, "unsupported-reasons": ["unproven-needs-turn-probe"]},
        proof={"fixture-id": "disposable-app-server", "test-run-id": "run-1", "artifact-digest": "sha256:" + "f" * 64,
               "verified-at": "2026-11-01T00:00:00Z"},
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    evidence.write_evidence(record, state_root=state_root)


def test_the_final_five_of_seven_record_is_not_enough_to_join(tmp_path: Path) -> None:
    adapter = join_readiness.adapter_identity(ADAPTER_REF)
    _partial_record(adapter, tmp_path)
    readiness = resolve_join_readiness("codex", "codex-app-server", facts=FACTS, adapter=adapter, state_root=tmp_path)
    assert not readiness.ready and readiness.outcome is SurfaceResolutionOutcome.UNSUPPORTED
    assert "unproven-prompt_delivery" in readiness.reasons
    assert "unproven-correlated_terminal_output" in readiness.reasons
    # The final measured record (5/7) satisfies concurrency; only the delivery claims keep it unsupported.
    assert "unproven-concurrency-safe-admission" not in readiness.reasons
    assert set(readiness.reasons) == {"unproven-prompt_delivery", "unproven-correlated_terminal_output"}


def test_a_different_executable_or_version_never_reuses_the_record(tmp_path: Path) -> None:
    adapter = join_readiness.adapter_identity(ADAPTER_REF)
    _partial_record(adapter, tmp_path)
    other = {**FACTS, "executable-digest": "sha256:" + "d" * 64}
    assert resolve_join_readiness("codex", "codex-app-server", facts=other, adapter=adapter,
                                  state_root=tmp_path).reasons == ("no-exact-evidence",)
    older = {**FACTS, "executable-version": "0.150.0"}
    assert resolve_join_readiness("codex", "codex-app-server", facts=older, adapter=adapter,
                                  state_root=tmp_path).reasons == ("version-not-declared",)


def test_the_shipped_matrix_still_routes_nothing(tmp_path: Path) -> None:
    from audiagentic.components.providers.services.session.join_authority import join_matrix

    rows = [row for row in join_matrix(state_root=tmp_path, facts={"codex": FACTS}) if row.provider_id == "codex"]
    app_server = [row for row in rows if row.surface_id == "codex-app-server"]
    assert app_server and all(row.outcome is not SurfaceResolutionOutcome.SUPPORTED for row in rows)
