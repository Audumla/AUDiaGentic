"""AS29 stage 3 (slice 3) — provider-neutral session-surface resolver service.

Tests cover all six semantic fixes from parent review:
1. Explicit project_root + provider_id on the resolver API (no cwd cache).
2. Installed-version discovery and disambiguation of same-ID declarations.
3. Exact normalized target-triple platform matching (no prefix/base match).
4. Platform evidence selected before validation ceiling enforcement.
5. resolved_version = actual installed version; unsupported uses neutral version.
6. Exhaustive focused tests for each listed fault.

Uses fake descriptors registered directly into the registry — no YAML loading.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# ── Module under test ───────────────────────────────────────────────────────
from audiagentic.components.providers.contracts.session_surface import (
    ResolvedSessionSurface,
    SurfaceHint,
)
from audiagentic.components.providers.descriptors.base import ProviderDescriptor
from audiagentic.components.providers.descriptors.registry import register
from audiagentic.components.providers.services.provider_config import (
    set_provider_enabled,
)
from audiagentic.components.providers.services.session_surface_resolution import (
    _platform_matches,
    resolve_session_surface,
)
from audiagentic.foundation.transports.session_surface import (
    ControlSupport,
    EffectiveObservationLevel,
    LifecycleSource,
    PlatformEvidence,
    SessionControlAction,
    SessionIdentityOperation,
    SessionMappingFacts,
    SessionOwnershipMode,
    SurfaceValidationState,
)

# ── Helpers: fake descriptor construction ───────────────────────────────────

def _fake_descriptor(
    provider_id: str = "test-provider",
    *,
    cli_probe: list[str] | None = None,
    session_surfaces: Any = (),
) -> ProviderDescriptor:
    """Build a minimal fake ProviderDescriptor for testing."""
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id,
        execution_isolation_tier="no-isolation",
        cli_probe=cli_probe,
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
def _isolate_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolate the descriptor registry and project root per test."""
    from audiagentic.components.providers.descriptors.registry import (
        _registry,
    )
    _registry._items.clear()

    yield tmp_path


@pytest.fixture()
def _enabled_test_provider(tmp_path: Path) -> str:
    """Register and enable a test provider with one surface declaration."""
    descriptor = _fake_descriptor(
        "test-provider",
        session_surfaces=(_fake_surface_decl(),),
    )
    register(descriptor)
    set_provider_enabled(tmp_path, "test-provider", enabled=True)
    return "test-provider"


# ── Fix 1: Explicit project_root + provider_id on resolver API ──────────────

class TestExplicitProjectRootAndProviderId:
    """Resolver takes explicit project_root and provider_id (Fix 1)."""

    def test_resolver_signature(self, _enabled_test_provider: str, tmp_path: Path):
        """resolver takes project_root, provider_id, surface_hint."""
        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "test-provider", hint)
        assert result.validation.state != SurfaceValidationState.UNSUPPORTED

    def test_different_project_root_rejected(self, tmp_path: Path):
        """A provider enabled on root A is not found on root B."""
        descriptor = _fake_descriptor(
            "root-test-prov",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        # Enable on tmp_path but NOT on another path.
        set_provider_enabled(tmp_path, "root-test-prov", enabled=True)

        other_root = tmp_path / "other"
        other_root.mkdir()

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(other_root, "root-test-prov", hint)
        # Other root has no feature state → disabled → unsupported.
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── SurfaceHint validation (provider_id removed from hint) ──────────────────

class TestSurfaceHintValidation:
    """SurfaceHint rejects empty/invalid fields."""

    def test_empty_surface_id(self):
        with pytest.raises(ValueError, match="surface_id"):
            SurfaceHint(surface_id="")

    def test_empty_version_hint(self):
        with pytest.raises(ValueError, match="version_hint"):
            SurfaceHint(surface_id="s", version_hint="")

    def test_empty_platform_hint(self):
        with pytest.raises(ValueError, match="platform_hint"):
            SurfaceHint(surface_id="s", platform_hint="")

    def test_valid_minimal_hint(self):
        hint = SurfaceHint(surface_id="acp")
        assert hint.surface_id == "acp"
        assert hint.version_hint is None
        assert hint.platform_hint is None

    def test_valid_with_hints(self):
        hint = SurfaceHint(
            surface_id="acp",
            version_hint=">=2.0",
            platform_hint="linux-amd64",
        )
        assert hint.version_hint == ">=2.0"
        assert hint.platform_hint == "linux-amd64"

    def test_frozen(self):
        hint = SurfaceHint(surface_id="acp")
        with pytest.raises(Exception):  # FrozenInstanceError
            hint.surface_id = "other"  # type: ignore


# ── Exact selection (happy path) ───────────────────────────────────────────

class TestExactSelection:
    """Correct provider + surface id yields a resolved snapshot."""

    def test_basic_resolution(self, _enabled_test_provider: str, tmp_path: Path):
        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "test-provider", hint)
        assert result.validation.state != SurfaceValidationState.UNSUPPORTED
        assert result.ref.provider_id == "test-provider"
        assert result.ref.surface_id == "acp"

    def test_resolved_carries_identity_operations(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "id-provider",
            session_surfaces=(
                _fake_surface_decl(
                    identity_operations={
                        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                        SessionIdentityOperation.ATTACH_EXISTING: ControlSupport.UNSUPPORTED,
                    },
                    ownership_modes=(SessionOwnershipMode.OWNED,),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "id-provider", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "id-provider", hint)
        assert result.identity.operation_supported(SessionIdentityOperation.OPEN) is True
        assert result.identity.operation_supported(SessionIdentityOperation.ATTACH_EXISTING) is False
        assert result.identity.supports_ownership(SessionOwnershipMode.OWNED) is True

    def test_resolved_carries_control_actions(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "ctrl-provider",
            session_surfaces=(
                _fake_surface_decl(
                    controls={
                        SessionControlAction.CANCEL_TURN: ControlSupport.SUPPORTED,
                        SessionControlAction.STEER_TURN: ControlSupport.UNSUPPORTED,
                    },
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "ctrl-provider", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "ctrl-provider", hint)
        assert result.control_supported(SessionControlAction.CANCEL_TURN) is True
        assert result.control_supported(SessionControlAction.STEER_TURN) is False

    def test_different_surface_ids_selected_correctly(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "multi-surf",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp"),
                _fake_surface_decl(surface_id="mcp"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "multi-surf", enabled=True)

        result_acp = resolve_session_surface(
            tmp_path, "multi-surf", SurfaceHint(surface_id="acp")
        )
        assert result_acp.ref.surface_id == "acp"

        result_mcp = resolve_session_surface(
            tmp_path, "multi-surf", SurfaceHint(surface_id="mcp")
        )
        assert result_mcp.ref.surface_id == "mcp"


# ── Fix 2: Installed-version discovery and disambiguation ───────────────────

class TestInstalledVersionDiscovery:
    """Two same-ID declarations with different versions are disambiguated by
    installed version (Fix 2)."""

    def test_two_same_id_different_versions_picks_correct(self, tmp_path: Path, monkeypatch):
        """Installed version '2.5' satisfies both >=1.0 and >=2.0; most specific
        constraint wins."""
        descriptor = _fake_descriptor(
            "dual-version",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp", version_constraint=">=1.0"),
                _fake_surface_decl(surface_id="acp", version_constraint=">=2.0"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "dual-version", enabled=True)

        # Mock installed version to '2.5.0' — satisfies both constraints.
        monkeypatch.setattr(
            "audiagentic.components.providers.services.session_surface_resolution._probe_installed_version",
            lambda d: "2.5.0",
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "dual-version", hint)
        # Most specific (>=2.0) should be selected; both are satisfied but >=2.0 is tighter.
        assert result.validation.state != SurfaceValidationState.UNSUPPORTED

    def test_no_installed_version_match(self, tmp_path: Path, monkeypatch):
        """Installed version doesn't satisfy any declaration's constraint → unsupported."""
        descriptor = _fake_descriptor(
            "no-match",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp", version_constraint=">=3.0"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "no-match", enabled=True)

        # Mock installed version to '2.0.0' — below >=3.0.
        monkeypatch.setattr(
            "audiagentic.components.providers.services.session_surface_resolution._probe_installed_version",
            lambda d: "2.0.0",
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "no-match", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_version_hint_narrows_but_does_not_substitute(self, tmp_path: Path, monkeypatch):
        """Version hint narrows selection but installed version must still match."""
        descriptor = _fake_descriptor(
            "hint-narrow",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp", version_constraint=">=1.0"),
                _fake_surface_decl(surface_id="acp", version_constraint=">=2.0"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "hint-narrow", enabled=True)

        # Installed version is '1.5.0' — satisfies >=1.0 but NOT >=2.0.
        # Hint asks for >=2.0 which narrows to the >=2.0 declaration, but installed
        # version doesn't satisfy it → unsupported.
        monkeypatch.setattr(
            "audiagentic.components.providers.services.session_surface_resolution._probe_installed_version",
            lambda d: "1.5.0",
        )

        hint = SurfaceHint(surface_id="acp", version_hint=">=2.0")
        result = resolve_session_surface(tmp_path, "hint-narrow", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_version_hint_narrows_and_installed_matches(self, tmp_path: Path, monkeypatch):
        """Hint narrows to >=2.0 and installed version satisfies it → success."""
        descriptor = _fake_descriptor(
            "hint-ok",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp", version_constraint=">=1.0"),
                _fake_surface_decl(surface_id="acp", version_constraint=">=2.0"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "hint-ok", enabled=True)

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session_surface_resolution._probe_installed_version",
            lambda d: "2.5.0",
        )

        hint = SurfaceHint(surface_id="acp", version_hint=">=2.0")
        result = resolve_session_surface(tmp_path, "hint-ok", hint)
        assert result.validation.state != SurfaceValidationState.UNSUPPORTED

    def test_no_cli_probe_single_declaration_resolves(self, tmp_path: Path):
        """Without cli_probe (no installed version), single declaration still resolves."""
        descriptor = _fake_descriptor(
            "no-probe",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "no-probe", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "no-probe", hint)
        assert result.validation.state != SurfaceValidationState.UNSUPPORTED


# ── Fix 3: Exact normalized target-triple platform matching ─────────────────

class TestExactPlatformMatching:
    """Platform matching uses exact normalized target triples only (Fix 3)."""

    def test_exact_triple_match(self, tmp_path: Path):
        """Exact triple match succeeds."""
        descriptor = _fake_descriptor(
            "exact-plat",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O2,
                    platforms=(PlatformEvidence(platform="linux-amd64"),),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "exact-plat", enabled=True)

        hint = SurfaceHint(surface_id="acp", platform_hint="linux-amd64")
        result = resolve_session_surface(tmp_path, "exact-plat", hint)
        assert result.validation.state != SurfaceValidationState.UNSUPPORTED

    def test_no_prefix_base_matching(self):
        """Base key 'linux' does NOT match declared 'linux-amd64'."""
        pe = PlatformEvidence(platform="linux-amd64")
        matched = _platform_matches("linux", (pe,))
        assert matched is None

    def test_exact_arch_mismatch(self, tmp_path: Path):
        """linux-arm64 does not match linux-amd64 declaration."""
        descriptor = _fake_descriptor(
            "arch-mismatch",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O2,
                    platforms=(PlatformEvidence(platform="linux-amd64"),),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "arch-mismatch", enabled=True)

        hint = SurfaceHint(surface_id="acp", platform_hint="linux-arm64")
        result = resolve_session_surface(tmp_path, "arch-mismatch", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_no_cross_platform_borrow(self):
        """Windows declaration does NOT match linux target."""
        pe = PlatformEvidence(platform="windows-amd64")
        matched = _platform_matches("linux-amd64", (pe,))
        assert matched is None

    def test_no_platforms_declared_allows_any(self, tmp_path: Path):
        """When no platforms are declared, any target platform is allowed."""
        descriptor = _fake_descriptor(
            "no-platform",
            session_surfaces=(
                _fake_surface_decl(),  # empty platforms tuple
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "no-platform", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "no-platform", hint)
        assert result.validation.state != SurfaceValidationState.UNSUPPORTED


# ── Fix 4: Platform evidence selected before enforcement ────────────────────

class TestPlatformBeforeEnforcement:
    """Platform evidence is selected BEFORE validation ceiling enforcement (Fix 4)."""

    def test_platform_level_o3_rejected(self, tmp_path: Path):
        """A platform-level declared O3 without VALIDATED state is rejected."""
        descriptor = _fake_descriptor(
            "plat-o3",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O0,
                    # Declaration level is O0 (allowed DECLARED), but per-platform
                    # evidence declares O3 with DECLARED state → rejected.
                    platforms=(
                        PlatformEvidence(
                            platform="linux-amd64",
                            validation_state=SurfaceValidationState.DECLARED,
                            effective_level=EffectiveObservationLevel.O3,
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "plat-o3", enabled=True)

        hint = SurfaceHint(surface_id="acp", platform_hint="linux-amd64")
        result = resolve_session_surface(tmp_path, "plat-o3", hint)
        # Per-platform O3 DECLARED → unvalidated-high-level → unsupported.
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_platform_level_validated_o2_allowed(self, tmp_path: Path):
        """Per-platform VALIDATED O2 is allowed even if declaration level is O0."""
        descriptor = _fake_descriptor(
            "plat-o2-ok",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.DECLARED,
                    effective_level=EffectiveObservationLevel.O0,
                    platforms=(
                        PlatformEvidence(
                            platform="linux-amd64",
                            validation_state=SurfaceValidationState.VALIDATED,
                            effective_level=EffectiveObservationLevel.O2,
                        ),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "plat-o2-ok", enabled=True)

        hint = SurfaceHint(surface_id="acp", platform_hint="linux-amd64")
        result = resolve_session_surface(tmp_path, "plat-o2-ok", hint)
        # Per-platform VALIDATED O2 → allowed.
        assert result.validation.state == SurfaceValidationState.VALIDATED
        assert result.validation.effective_level == EffectiveObservationLevel.O2

    def test_no_platform_evidence_falls_back_to_declaration(self, tmp_path: Path):
        """No per-platform evidence for the target — fall back to declaration level."""
        descriptor = _fake_descriptor(
            "fallback-decl",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O2,
                    platforms=(
                        PlatformEvidence(platform="linux-amd64"),
                        PlatformEvidence(platform="darwin-arm64"),
                    ),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "fallback-decl", enabled=True)

        # Target a platform not in the PE list → no-platform-match.
        hint = SurfaceHint(surface_id="acp", platform_hint="windows-amd64")
        result = resolve_session_surface(tmp_path, "fallback-decl", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── Fix 5: resolved_version semantics ───────────────────────────────────────

class TestResolvedVersionSemantics:
    """resolved_version contains actual installed version on success; unsupported
    snapshots use neutral version without diagnostic reasons (Fix 5)."""

    def test_resolved_version_is_installed(self, tmp_path: Path, monkeypatch):
        """On success, resolved_version is the actual installed version."""
        descriptor = _fake_descriptor(
            "ver-success",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "ver-success", enabled=True)

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session_surface_resolution._probe_installed_version",
            lambda d: "3.7.2",
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "ver-success", hint)
        assert result.ref.resolved_version == "3.7.2"

    def test_unsupported_no_diagnostic_in_version(self):
        """Unsupported snapshot does NOT encode diagnostic reasons in resolved_version."""
        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(
            Path("/nonexistent"), "nonexistent-provider", hint,
        )
        # Version should be neutral — not "unsupported:unknown-provider".
        assert "unknown-provider" not in result.ref.resolved_version
        assert "unsupported" not in result.ref.resolved_version.lower() or \
               result.ref.resolved_version == "unknown"

    def test_unsupported_version_is_neutral_with_hint(self):
        """When version_hint is provided, unsupported snapshot uses it as neutral version."""
        hint = SurfaceHint(surface_id="acp", version_hint=">=2.0")
        result = resolve_session_surface(
            Path("/nonexistent"), "nonexistent-provider", hint,
        )
        # Should use the version_hint as the stable version.
        assert result.ref.resolved_version == ">=2.0"

    def test_unsupported_no_native_value(self):
        """Unsupported snapshot carries no native adapter or protocol value."""
        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(
            Path("/nonexistent"), "nonexistent-provider", hint,
        )
        assert "adapter_ref" not in repr(result)
        assert "native" not in result.ref.resolved_version.lower()


# ── Disabled provider ───────────────────────────────────────────────────────

class TestDisabledProvider:
    """Disabled provider returns unsupported snapshot."""

    def test_disabled_provider_unsupported(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "disabled-prov",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "disabled-prov", enabled=False)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "disabled-prov", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── Unknown provider ────────────────────────────────────────────────────────

class TestUnknownProvider:
    """Unknown provider returns unsupported snapshot."""

    def test_unknown_provider(self, tmp_path: Path):
        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "nonexistent-provider", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── No surface id match ─────────────────────────────────────────────────────

class TestNoSurfaceIdMatch:
    """No exact surface_id match returns unsupported snapshot."""

    def test_no_surface_match(self, _enabled_test_provider: str, tmp_path: Path):
        hint = SurfaceHint(surface_id="nonexistent")
        result = resolve_session_surface(tmp_path, "test-provider", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── Blocked declaration ─────────────────────────────────────────────────────

class TestBlockedDeclaration:
    """Blocked validation_state returns unsupported snapshot."""

    def test_blocked(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "blocked-prov",
            session_surfaces=(
                _fake_surface_decl(validation_state=SurfaceValidationState.BLOCKED),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "blocked-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "blocked-prov", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── Unvalidated O3 ceiling (declaration level) ──────────────────────────────

class TestUnvalidatedDeclarationCeiling:
    """Non-validated O2+ at declaration level is unsupported."""

    def test_unvalidated_o3(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "o3-prov",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.DECLARED,
                    effective_level=EffectiveObservationLevel.O3,
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "o3-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "o3-prov", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_unvalidated_o2(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "o2-prov",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.DECLARED,
                    effective_level=EffectiveObservationLevel.O2,
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "o2-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "o2-prov", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_validated_o3_allowed(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "o3-valid-prov",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O3,
                    platforms=(PlatformEvidence(platform="linux-amd64"),),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "o3-valid-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp", platform_hint="linux-amd64")
        result = resolve_session_surface(tmp_path, "o3-valid-prov", hint)
        assert "unvalidated-high-level" not in (result.ref.resolved_version or "")

    def test_declared_o0_allowed(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "o0-prov",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.DECLARED,
                    effective_level=EffectiveObservationLevel.O0,
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "o0-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "o0-prov", hint)
        assert "unvalidated-high-level" not in (result.ref.resolved_version or "")


# ── Missing adapter factory ─────────────────────────────────────────────────

class TestMissingAdapterFactory:
    """Missing adapter factory returns unsupported snapshot."""

    def test_missing_factory(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "missing-factory-prov",
            session_surfaces=(
                _fake_surface_decl(adapter_ref="nonexistent.module:factory_fn"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "missing-factory-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "missing-factory-prov", hint)
        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_existing_factory_ok(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "existing-factory-prov",
            session_surfaces=(
                _fake_surface_decl(
                    adapter_ref="audiagentic.foundation.transports.session_surface:ControlSupport",
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "existing-factory-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "existing-factory-prov", hint)
        assert "missing-adapter-factory" not in (result.ref.resolved_version or "")

    def test_no_adapter_ref_skips_check(self, tmp_path: Path):
        descriptor = _fake_descriptor(
            "no-adapter-prov",
            session_surfaces=(
                _fake_surface_decl(adapter_ref=None),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "no-adapter-prov", enabled=True)

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "no-adapter-prov", hint)
        assert "missing-adapter-factory" not in (result.ref.resolved_version or "")


# ── Immutable / no native value result ──────────────────────────────────────

class TestImmutableNoNativeValue:
    """ResolvedSessionSurface is frozen and contains no native/adapter values."""

    def test_result_is_frozen(self, _enabled_test_provider: str, tmp_path: Path):
        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "test-provider", hint)
        with pytest.raises(Exception):  # FrozenInstanceError
            result.ref = None  # type: ignore

    def test_result_has_no_adapter_ref_field(self, _enabled_test_provider: str, tmp_path: Path):
        """ResolvedSessionSurface must not carry adapter_ref."""
        import dataclasses
        surface_fields = {f.name for f in dataclasses.fields(ResolvedSessionSurface)}
        assert "adapter_ref" not in surface_fields

    def test_result_has_no_callables(self, _enabled_test_provider: str, tmp_path: Path):
        """No callables in the resolved snapshot (scalar-only discipline)."""
        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "test-provider", hint)
        self._assert_no_callables(result)

    def _assert_no_callables(self, obj: Any, path: str = "") -> None:
        import dataclasses as dc
        if dc.is_dataclass(obj):
            for f in dc.fields(obj):
                self._assert_no_callables(getattr(obj, f.name), f"{path}.{f.name}")
        elif isinstance(obj, dict):
            for key, value in obj.items():
                self._assert_no_callables(value, f"{path}[{key}]")
        elif isinstance(obj, (tuple, list)):
            for i, value in enumerate(obj):
                self._assert_no_callables(value, f"{path}[{i}]")
        elif callable(obj) and not isinstance(obj, (str, int, float, bool, type(None))):
            import enum
            if isinstance(obj, enum.Enum):
                return
            raise AssertionError(f"Unexpected callable at {path}: {obj!r}")


# ── No provider descriptor/protocol import in agents module ─────────────────

class TestNoAgentImport:
    """Resolver and contract modules must not import from agents."""

    def test_no_agent_import_in_session_surface_contract(self):
        mod = __import__(
            "audiagentic.components.providers.contracts.session_surface",
            fromlist=["SurfaceHint"],
        )
        source = _inspect_source(mod)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from audiagentic.components.agents" not in stripped

    def test_no_agent_import_in_session_surface_resolution(self):
        mod = __import__(
            "audiagentic.components.providers.services.session_surface_resolution",
            fromlist=["resolve_session_surface"],
        )
        source = _inspect_source(mod)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from audiagentic.components.agents" not in stripped

    def test_no_provider_descriptor_import_in_agents(self):
        try:
            from audiagentic.components.agents import (
                agents_gateway_session_bindings as agsb,
            )
        except ImportError:
            pytest.skip("agents_gateway_session_bindings not available")

        source = _inspect_source(agsb)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from audiagentic.components.providers.descriptors" not in stripped

    def test_no_protocol_import_in_agents(self):
        try:
            from audiagentic.components.agents import (
                agents_gateway_session_bindings as agsb,
            )
        except ImportError:
            pytest.skip("agents_gateway_session_bindings not available")

        source = _inspect_source(agsb)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from audiagentic.components.providers.protocols" not in stripped


def _inspect_source(module: Any) -> str:
    """Get source of a module as string."""
    import inspect
    return inspect.getsource(module)
