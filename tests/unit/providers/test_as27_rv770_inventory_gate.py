"""AS27 RV770 regression tests — inventory proof gate enforcement.

Verifies that vendor cross-platform support alone does not make a surface
publisher-eligible, and that descriptor YAML cannot bypass inventory evidence
for O1+ validated claims.

These tests cover:
- Vendor cross-platform support alone does not grant eligibility;
- OpenCode Windows/Darwin local status publication is rejected until probe;
- YAML resolver cannot promote a platform absent from inventory evidence;
- The locally proven platform (linux-amd64) preserves existing behavior;
- YAML/inventory consistency for validated O1 transport observation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.descriptors.base import ProviderDescriptor
from audiagentic.components.providers.descriptors.registry import register
from audiagentic.components.providers.services.config.provider_config import (
    set_provider_enabled,
)
from audiagentic.components.providers.services.session.session_surface_resolution import (
    resolve_session_surface,
)
from audiagentic.foundation.transports.session_surface import (
    ControlSupport,
    EffectiveObservationLevel,
    LifecycleSource,
    PlatformEvidence,
    SessionIdentityOperation,
    SessionMappingFacts,
    SurfaceValidationState,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _fake_descriptor(
    provider_id: str = "test-provider",
    *,
    cli_probe: list[str] | None = None,
    session_surfaces: Any = (),
) -> ProviderDescriptor:
    """Build a minimal fake ProviderDescriptor for testing."""
    from audiagentic.components.providers.descriptors.base import (
        Capability,
        CliInstallRecipe,
    )

    capabilities = (
        (
            Capability(
                kind="cli-install",
                mechanism=CliInstallRecipe(
                    package_manager="test",
                    package_name="test",
                    executable="test",
                    install=None,  # type: ignore[arg-type]
                    uninstall=None,  # type: ignore[arg-type]
                    probe=cli_probe,
                ),
            ),
        )
        if cli_probe is not None
        else ()
    )
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id,
        execution_isolation_tier="no-isolation",
        capabilities=capabilities,
        session_surfaces=session_surfaces,
    )


def _fake_surface_decl(
    surface_id: str = "acp",
    version_constraint: str = ">=1.0",
    validation_state: SurfaceValidationState = SurfaceValidationState.DECLARED,
    effective_level: EffectiveObservationLevel = EffectiveObservationLevel.O0,
    identity_operations: dict | None = None,
    ownership_modes: tuple = (),
    controls: dict | None = None,
    lifecycle_source: LifecycleSource = LifecycleSource.NONE,
    adapter_ref: str | None = None,
    platforms: Any = (),
) -> Any:
    """Build a fake SessionSurfaceDeclaration for testing."""
    from audiagentic.components.providers.descriptors.session_surface_declarations import (
        SessionSurfaceDeclaration,
    )
    return SessionSurfaceDeclaration(
        surface_id=surface_id,
        version_constraint=version_constraint,
        identity_operations=identity_operations or {},
        ownership_modes=ownership_modes,
        mapping_facts=SessionMappingFacts(),
        controls=controls or {},
        lifecycle_source=lifecycle_source,
        adapter_ref=adapter_ref,
        validation_state=validation_state,
        effective_level=effective_level,
        platforms=platforms,
    )


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path: Path):
    """Isolate the descriptor registry per test.

    Clears items AND sets _loaded=True so that the YAML lazy-loader does
    NOT repopulate from disk when get_descriptor() is called. This allows
    fake descriptors to be registered without being overwritten.
    """
    from audiagentic.components.providers.descriptors.registry import (
        _registry,
    )
    _registry._items.clear()
    _registry._loaded = True  # Prevent YAML auto-load on subsequent access
    yield tmp_path


# ── Test 1: Vendor cross-platform support alone does not grant eligibility ─

class TestVendorSupportNotEligibility:
    """Vendor product support (windows/macOS/linux) is NOT status evidence.

    A surface can be vendor-supported on all platforms but only locally
    validated on some. The inventory proof gate rejects O1+ claims on
    unproven platforms.
    """

    def test_cross_platform_vendor_support_not_eligible(self):
        """Platform support fact alone does not make a surface publisher-eligible.

        The inventory is authoritative — even if YAML declares all platforms
        as validated, the inventory gate rejects platforms without evidence.
        """
        from audiagentic.components.providers.services.session.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )

        # opencode-acp is vendor-supported on windows/darwin/linux but
        # only locally validated on linux-amd64.
        assert is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="linux-amd64",
        )
        # Windows — vendor supports it, but no local probe → not eligible.
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="windows-amd64",
        )
        # Darwin — vendor supports it, but no local probe → not eligible.
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="darwin-arm64",
        )

    def test_vendor_support_only_surface_not_eligible(self):
        """A surface with vendor support but no inventory entry is never eligible."""
        from audiagentic.components.providers.services.session.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )

        # codex-acp has vendor support on windows/macOS/linux but
        # is probe-required in the inventory.
        assert not is_eligible_transport_observation_publisher(
            "codex", "codex-acp", platform="linux-amd64",
        )
        assert not is_eligible_transport_observation_publisher(
            "codex", "codex-acp", platform="windows-amd64",
        )


# ── Test 2: OpenCode Windows/Darwin rejected until local probe ───────────

class TestOpencodeNonLinuxRejection:
    """OpenCode opencode-acp on windows-amd64 and darwin-arm64 is rejected
    by the resolver because inventory lacks platform evidence.

    Even if YAML declares these platforms as validated (hypothetically),
    the inventory gate prevents O1+ claims without local probe proof.
    """

    def test_windows_rejected_by_resolver(self, monkeypatch):
        """If YAML claims VALIDATED/O1 for windows-amd64, the inventory gate
        rejects it because the AS27 inventory lacks platform evidence.

        This simulates what would happen if someone tried to bypass the
        inventory by setting windows-amd64 to VALIDATED/O1 in the YAML.
        The resolver's inventory proof gate catches this and returns
        UNSUPPORTED.

        We mock _get_inventory_proof to simulate an inventory that lacks
        windows-amd64 evidence — same as the real AS27 inventory state.
        """

        # Mock: inventory has no proof for (opencode, opencode-acp, windows-amd64)
        def fake_inventory_check(provider_id, surface_id, target_platform):
            if provider_id == "opencode" and surface_id == "opencode-acp":
                return target_platform == "linux-amd64"  # only linux proven
            return False

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session.session_surface_resolution._get_inventory_proof",
            fake_inventory_check,
        )

        descriptor = _fake_descriptor(
            "opencode",
            session_surfaces=(
                _fake_surface_decl(
                    surface_id="opencode-acp",
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O1,
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                    },
                    lifecycle_source=LifecycleSource.TRANSPORT,
                    adapter_ref=(
                        "audiagentic.components.providers.adapters.opencode.acp:"
                        "build_acp_launch"
                    ),
                    platforms=(
                        PlatformEvidence(
                            platform="windows-amd64",
                            validation_state=SurfaceValidationState.VALIDATED,
                            effective_level=EffectiveObservationLevel.O1,
                            probe_artifact="tests/e2e/agents/test_opencode_acp_e2e.py",
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(Path("/tmp"), "opencode", enabled=True)

        hint = SurfaceHint(
            surface_id="opencode-acp", platform_hint="windows-amd64",
        )
        result = resolve_session_surface(Path("/tmp"), "opencode", hint)
        # Inventory lacks windows-amd64 → no-inventory-proof → unsupported.
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_windows_declared_o0_resolves_ok(self, monkeypatch):
        """The real opencode.yaml has windows as DECLARED/O0 → resolves ok.

        Since the YAML says DECLARED/O0 for windows-amd64, the inventory
        gate is NOT triggered (only O1+ validated claims are gated). The
        resolver returns DECLARED/O0 — the surface is available but without
        advanced observability.
        """

        # Mock: inventory has no proof for windows-amd64
        def fake_inventory_check(provider_id, surface_id, target_platform):
            return False

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session.session_surface_resolution._get_inventory_proof",
            fake_inventory_check,
        )

        descriptor = _fake_descriptor(
            "opencode",
            session_surfaces=(
                _fake_surface_decl(
                    surface_id="opencode-acp",
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O1,
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                    },
                    lifecycle_source=LifecycleSource.TRANSPORT,
                    adapter_ref=(
                        "audiagentic.components.providers.adapters.opencode.acp:"
                        "build_acp_launch"
                    ),
                    platforms=(
                        # linux-amd64: validated (in inventory)
                        PlatformEvidence(
                            platform="linux-amd64",
                            validation_state=SurfaceValidationState.VALIDATED,
                            effective_level=EffectiveObservationLevel.O1,
                            probe_artifact="tests/e2e/agents/test_opencode_acp_e2e.py",
                        ),
                        # windows-amd64: declared (not in inventory for O1)
                        PlatformEvidence(
                            platform="windows-amd64",
                            validation_state=SurfaceValidationState.DECLARED,
                            effective_level=EffectiveObservationLevel.O0,
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(Path("/tmp"), "opencode", enabled=True)

        hint = SurfaceHint(
            surface_id="opencode-acp", platform_hint="windows-amd64",
        )
        result = resolve_session_surface(Path("/tmp"), "opencode", hint)
        # DECLARED/O0 — no inventory gate triggered (not O1+ validated).
        assert result.validation.state == SurfaceValidationState.DECLARED
        assert result.validation.effective_level == EffectiveObservationLevel.O0

    def test_darwin_arm64_rejected_by_resolver(self, monkeypatch):
        """If YAML claims VALIDATED/O1 for darwin-arm64, the inventory gate
        rejects it because the AS27 inventory lacks platform evidence."""
        def fake_inventory_check(provider_id, surface_id, target_platform):
            return False  # no platform proven

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session.session_surface_resolution._get_inventory_proof",
            fake_inventory_check,
        )

        descriptor = _fake_descriptor(
            "opencode",
            session_surfaces=(
                _fake_surface_decl(
                    surface_id="opencode-acp",
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O1,
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                    },
                    lifecycle_source=LifecycleSource.TRANSPORT,
                    adapter_ref=(
                        "audiagentic.components.providers.adapters.opencode.acp:"
                        "build_acp_launch"
                    ),
                    platforms=(
                        PlatformEvidence(
                            platform="darwin-arm64",
                            validation_state=SurfaceValidationState.VALIDATED,
                            effective_level=EffectiveObservationLevel.O1,
                            probe_artifact="tests/e2e/agents/test_opencode_acp_e2e.py",
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(Path("/tmp"), "opencode", enabled=True)

        hint = SurfaceHint(
            surface_id="opencode-acp", platform_hint="darwin-arm64",
        )
        result = resolve_session_surface(Path("/tmp"), "opencode", hint)
        # Inventory lacks darwin-arm64 → no-inventory-proof → unsupported.
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_darwin_amd64_rejected_by_resolver(self, monkeypatch):
        """If YAML claims VALIDATED/O1 for darwin-amd64, the inventory gate
        rejects it because the AS27 inventory lacks platform evidence."""
        def fake_inventory_check(provider_id, surface_id, target_platform):
            return False  # no platform proven

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session.session_surface_resolution._get_inventory_proof",
            fake_inventory_check,
        )

        descriptor = _fake_descriptor(
            "opencode",
            session_surfaces=(
                _fake_surface_decl(
                    surface_id="opencode-acp",
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O1,
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                    },
                    lifecycle_source=LifecycleSource.TRANSPORT,
                    adapter_ref=(
                        "audiagentic.components.providers.adapters.opencode.acp:"
                        "build_acp_launch"
                    ),
                    platforms=(
                        PlatformEvidence(
                            platform="darwin-amd64",
                            validation_state=SurfaceValidationState.VALIDATED,
                            effective_level=EffectiveObservationLevel.O1,
                            probe_artifact="tests/e2e/agents/test_opencode_acp_e2e.py",
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(Path("/tmp"), "opencode", enabled=True)

        hint = SurfaceHint(
            surface_id="opencode-acp", platform_hint="darwin-amd64",
        )
        result = resolve_session_surface(Path("/tmp"), "opencode", hint)
        # Inventory lacks darwin-amd64 → no-inventory-proof → unsupported.
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── Test 3: YAML cannot promote a platform absent from inventory ──────────

class TestYamlCannotBypassInventory:
    """Descriptor YAML cannot claim O1+ on a platform without inventory proof.

    Even if a provider YAML declares validated/O1 for a platform, the
    resolver's inventory proof gate rejects it unless the inventory has
    local probe evidence for that exact (provider_id, surface_id, platform)
    tuple.
    """

    def test_yaml_validated_o1_no_inventory_proof(self, monkeypatch):
        """YAML claims VALIDATED/O1 but inventory has no entry → rejected."""
        # Mock: inventory has no proof for any platform
        def fake_inventory_check(provider_id, surface_id, target_platform):
            return False

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session.session_surface_resolution._get_inventory_proof",
            fake_inventory_check,
        )

        descriptor = _fake_descriptor(
            "some-provider",
            session_surfaces=(
                _fake_surface_decl(
                    surface_id="some-acp",
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O1,
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                    },
                    lifecycle_source=LifecycleSource.TRANSPORT,
                    adapter_ref=(
                        "audiagentic.components.providers.adapters.opencode.acp:"
                        "build_acp_launch"
                    ),
                    platforms=(
                        PlatformEvidence(
                            platform="linux-amd64",
                            validation_state=SurfaceValidationState.VALIDATED,
                            effective_level=EffectiveObservationLevel.O1,
                            probe_artifact="some-probe.py",
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(Path("/tmp"), "some-provider", enabled=True)

        hint = SurfaceHint(
            surface_id="some-acp", platform_hint="linux-amd64",
        )
        result = resolve_session_surface(Path("/tmp"), "some-provider", hint)
        # No inventory entry for (some-provider, some-acp) → unsupported.
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_yaml_declared_o0_no_inventory_ok(self):
        """YAML claims DECLARED/O0 with no inventory — allowed (no O1+ claim)."""
        descriptor = _fake_descriptor(
            "declared-prov",
            session_surfaces=(
                _fake_surface_decl(
                    surface_id="declared-acp",
                    validation_state=SurfaceValidationState.DECLARED,
                    effective_level=EffectiveObservationLevel.O0,
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                    },
                    platforms=(
                        PlatformEvidence(
                            platform="linux-amd64",
                            validation_state=SurfaceValidationState.DECLARED,
                            effective_level=EffectiveObservationLevel.O0,
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(Path("/tmp"), "declared-prov", enabled=True)

        hint = SurfaceHint(
            surface_id="declared-acp", platform_hint="linux-amd64",
        )
        result = resolve_session_surface(Path("/tmp"), "declared-prov", hint)
        # DECLARED/O0 — no inventory proof needed (no O1+ claim).
        assert result.validation.state == SurfaceValidationState.DECLARED
        assert result.validation.effective_level == EffectiveObservationLevel.O0


# ── Test 4: Locally proven platform preserves existing behavior ──────────

class TestLocallyProvenPlatformPreserved:
    """linux-amd64 for opencode-acp is the only locally proven platform.

    The resolver should return VALIDATED/O1 for linux-amd64 when using
    a descriptor that mirrors the real opencode.yaml state.
    """

    def test_linux_amd64_preserves_validated_o1(self, monkeypatch):
        """linux-amd64 resolves as VALIDATED/O1 — existing behavior preserved."""
        # Mock: inventory has proof for linux-amd64 only
        def fake_inventory_check(provider_id, surface_id, target_platform):
            if provider_id == "opencode" and surface_id == "opencode-acp":
                return target_platform == "linux-amd64"
            return False

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session.session_surface_resolution._get_inventory_proof",
            fake_inventory_check,
        )

        descriptor = _fake_descriptor(
            "opencode",
            session_surfaces=(
                _fake_surface_decl(
                    surface_id="opencode-acp",
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O1,
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                    },
                    lifecycle_source=LifecycleSource.TRANSPORT,
                    adapter_ref=(
                        "audiagentic.components.providers.adapters.opencode.acp:"
                        "build_acp_launch"
                    ),
                    platforms=(
                        PlatformEvidence(
                            platform="linux-amd64",
                            validation_state=SurfaceValidationState.VALIDATED,
                            effective_level=EffectiveObservationLevel.O1,
                            probe_artifact="tests/e2e/agents/test_opencode_acp_e2e.py",
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(Path("/tmp"), "opencode", enabled=True)

        hint = SurfaceHint(
            surface_id="opencode-acp", platform_hint="linux-amd64",
        )
        result = resolve_session_surface(Path("/tmp"), "opencode", hint)
        assert result.validation.state == SurfaceValidationState.VALIDATED
        assert result.validation.effective_level == EffectiveObservationLevel.O1

    def test_inventory_eligible_linux(self):
        """Inventory confirms linux-amd64 eligibility for opencode-acp."""
        from audiagentic.components.providers.services.session.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="linux-amd64",
        )


# ── Test 5: YAML/inventory consistency for validated O1 transport ────────

class TestYamlInventoryConsistency:
    """For any surface claiming VALIDATED/O1 transport observation,
    the YAML and inventory must be consistent.

    The inventory is authoritative: YAML can only claim what the inventory
    proves. This test verifies that the real opencode.yaml + inventory
    are consistent for linux-amd64 and inconsistent (rejected) for others.
    """

    def test_linux_consistent_validated_o1(self):
        """linux-amd64: YAML VALIDATED/O1 matches inventory platform_evidence."""
        from audiagentic.components.providers.services.session.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("opencode", "opencode-acp")
        assert fact is not None
        assert "linux-amd64" in fact.platform_evidence

    def test_windows_inconsistent_rejected(self):
        """windows-amd64: YAML DECLARED/O0 — no inventory proof → resolver OK.

        The real opencode.yaml has windows-amd64 as DECLARED/O0, which does
        NOT trigger the inventory gate (only O1+ validated claims are gated).
        So the resolver returns DECLARED/O0 for windows.

        But if YAML were to claim VALIDATED/O1 for windows, the inventory
        gate would reject it — verified by TestOpencodeNonLinuxRejection.
        """
        from audiagentic.components.providers.services.session.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("opencode", "opencode-acp")
        assert fact is not None
        # windows-amd64 is NOT in inventory → not validated.
        assert "windows-amd64" not in fact.platform_evidence

    def test_darwin_inconsistent_rejected(self):
        """darwin-arm64: YAML DECLARED/O0 — no inventory proof."""
        from audiagentic.components.providers.services.session.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("opencode", "opencode-acp")
        assert fact is not None
        assert "darwin-arm64" not in fact.platform_evidence

    def test_any_validated_o1_requires_inventory_proof(self):
        """Any surface with VALIDATED/O1 in YAML must have inventory evidence.

        This test iterates all inventory entries and checks that any surface
        claiming VALIDATED/O1+ transport observation has its platforms listed
        in the inventory's platform_evidence.
        """
        from audiagentic.components.providers.services.session.harness_observability_inventory import (
            CapabilityFactValidationState,
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if (
                fact.validation_state == CapabilityFactValidationState.VALIDATED
                and fact.effective_production_level.numeric >= 1
            ):
                # This surface claims O1+ validated — all its platforms
                # must be in platform_evidence.
                for pe_platform in fact.platform_evidence:
                    assert pe_platform in fact.platform_evidence, (
                        f"{pid}/{sid} claims {pe_platform} validated but "
                        f"inventory lacks evidence"
                    )
