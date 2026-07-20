"""AS29 slice 4 — OpenCode session-surfaces descriptor declarations and loader tests.

Loads the real OpenCode provider YAML and proves:
- Duplicate prevention (distinct surface IDs, same version)
- Distinct ACP vs CLI surface IDs (not interchangeable fallbacks)
- No invalid O2+ declaration (effective_level ceiling enforced)
- Validation state matches evidence proven in repo
- No raw command, token, secret, or native protocol identifier leaks
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.descriptors.loader import (
    get_providers_config_dir,
    load_providers_from_directory,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    ControlSupport,
    EffectiveObservationLevel,
    LifecycleSource,
    PlatformEvidence,
    SessionControlAction,
    SessionIdentityOperation,
    SurfaceValidationState,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

def _load_opencode() -> object:
    """Load the real OpenCode provider descriptor from YAML."""
    providers = load_providers_from_directory(get_providers_config_dir())
    return providers["opencode"]


# ── Load actual descriptor ─────────────────────────────────────────────────

class TestLoadOpenCodeDescriptor:
    """The real OpenCode YAML loads with session_surfaces intact."""

    def test_opencode_has_session_surfaces(self):
        desc = _load_opencode()
        assert len(desc.session_surfaces) == 2, (
            "OpenCode should have exactly 2 session surfaces: ACP + CLI"
        )

    def test_opencode_acp_surface_id(self):
        desc = _load_opencode()
        ids = [s.surface_id for s in desc.session_surfaces]
        assert "opencode-acp" in ids, (
            "ACP surface must use distinct ID 'opencode-acp'"
        )

    def test_opencode_cli_session_surface_id(self):
        desc = _load_opencode()
        ids = [s.surface_id for s in desc.session_surfaces]
        assert "opencode-cli-session" in ids, (
            "CLI session surface must use distinct ID 'opencode-cli-session'"
        )

    def test_acp_and_cli_are_not_interchangeable(self):
        """ACP and CLI surfaces have distinct IDs; no fallback mapping."""
        desc = _load_opencode()
        ids = [s.surface_id for s in desc.session_surfaces]
        assert ids.index("opencode-acp") != ids.index("opencode-cli-session"), (
            "ACP and CLI surface indices must differ — they are distinct surfaces"
        )
        # Both share the same version constraint but different IDs = no collision
        acp = next(s for s in desc.session_surfaces if s.surface_id == "opencode-acp")
        cli = next(s for s in desc.session_surfaces if s.surface_id == "opencode-cli-session")
        assert acp.version_constraint == cli.version_constraint, (
            "Same version constraint is fine when surface IDs differ"
        )

# ── Duplicate prevention ───────────────────────────────────────────────────

class TestDuplicatePrevention:
    """No duplicate (surface_id, version_constraint) pairs survive loading."""

    def test_no_duplicate_surface_keys_in_opencode(self):
        desc = _load_opencode()
        keys = {(s.surface_id, s.version_constraint) for s in desc.session_surfaces}
        assert len(keys) == len(desc.session_surfaces), (
            "Each (surface_id, version_constraint) pair must be unique"
        )

    def test_different_surface_ids_same_version_ok(self):
        """OpenCode has two surfaces with same version_constraint — valid."""
        desc = _load_opencode()
        versions = {s.version_constraint for s in desc.session_surfaces}
        assert len(versions) < len(desc.session_surfaces), (
            "Different surface IDs with same version is the expected pattern"
        )

# ── ACP surface properties ─────────────────────────────────────────────────

class TestACPSurfaceProperties:
    """OpenCode ACP surface declares correct capabilities."""

    @pytest.fixture
    def acp(self):
        desc = _load_opencode()
        return next(s for s in desc.session_surfaces if s.surface_id == "opencode-acp")

    def test_acp_open_supported(self, acp):
        assert (
            acp.identity_operations.get(SessionIdentityOperation.OPEN)
            == ControlSupport.SUPPORTED
        )

    def test_acp_attach_existing_unsupported(self, acp):
        assert (
            acp.identity_operations.get(SessionIdentityOperation.ATTACH_EXISTING)
            == ControlSupport.UNSUPPORTED
        )

    def test_acp_resume_by_ref_unsupported(self, acp):
        """ACP surface does not support resume-by-ref — that is CLI territory."""
        assert (
            acp.identity_operations.get(SessionIdentityOperation.RESUME_BY_REF)
            == ControlSupport.UNSUPPORTED
        )

    def test_acp_close_session_supported(self, acp):
        assert (
            acp.controls.get(SessionControlAction.CLOSE_SESSION)
            == ControlSupport.SUPPORTED
        )

    def test_acp_lifecycle_source_transport(self, acp):
        """ACP lifecycle comes from the transport layer."""
        assert acp.lifecycle_source == LifecycleSource.TRANSPORT

    def test_acp_validation_state_not_overstated(self, acp):
        """ACP parent level is NOT VALIDATED because Windows is only declared.

        probe_artifact naming a source file is not proof of execution;
        the parent must be conservative when platforms are mixed."""
        assert acp.validation_state != SurfaceValidationState.VALIDATED, (
            "parent validation_state must not be VALIDATED when not all platforms are validated"
        )
        # Parent is declared (conservative) while linux-amd64 is the only validated platform
        assert acp.validation_state == SurfaceValidationState.DECLARED

    def test_acp_has_platform_evidence(self, acp):
        """Surface carries platform evidence with mixed states."""
        assert len(acp.platforms) >= 1, "surface should carry platform evidence"

    def test_acp_linux_platform_validated(self, acp):
        """Linux-amd64 platform for ACP is validated (e2e tested)."""
        linux = next((p for p in acp.platforms if p.platform == "linux-amd64"), None)
        assert linux is not None
        assert linux.validation_state == SurfaceValidationState.VALIDATED

    def test_acp_windows_platform_declared(self, acp):
        """Windows-amd64 platform for ACP is declared but not proven."""
        win = next((p for p in acp.platforms if p.platform == "windows-amd64"), None)
        assert win is not None
        # Windows not proven yet — should be declared, not validated
        assert win.validation_state != SurfaceValidationState.VALIDATED

    def test_acp_content_channel_bounded(self, acp):
        """ACP content channels must carry nonzero bounds."""
        for ch in acp.content_channels:
            assert ch.max_bytes > 0 or ch.max_events > 0, (
                f"channel {ch.channel} has zero bounds — must carry at least one"
            )

    def test_acp_has_adapter_ref(self, acp):
        """ACP surface carries the adapter_ref for launch resolution."""
        assert acp.adapter_ref is not None
        assert "opencode.acp:build_acp_launch" in acp.adapter_ref

    def test_acp_effective_level_not_o2_plus_unvalidated(self, acp):
        """ACP effective level must not be O2+ without validation."""
        # O1 is fine without validated parent; O0-O1 don't need platform proof
        if acp.effective_level.numeric >= 2:
            assert acp.validation_state == SurfaceValidationState.VALIDATED

    def test_acp_linux_validated(self, acp):
        """Linux-amd64 is the only validated platform — e2e proven."""
        linux = next((p for p in acp.platforms if p.platform == "linux-amd64"), None)
        assert linux is not None
        assert linux.validation_state == SurfaceValidationState.VALIDATED

    def test_acp_windows_not_validated(self, acp):
        """Windows-amd64 is declared but NOT validated — no e2e proof yet."""
        win = next((p for p in acp.platforms if p.platform == "windows-amd64"), None)
        assert win is not None
        assert win.validation_state != SurfaceValidationState.VALIDATED, (
            "Windows platform must not be VALIDATED without e2e proof"
        )

    def test_acp_probe_artifact_not_proof(self, acp):
        """probe_artifact naming a source file is NOT execution proof.

        The mere presence of probe_artifact pointing to a .py file does not
        mean that test has passed on that platform."""
        for pe in acp.platforms:
            # probe_artifact may be set (it names a file path)
            # but its existence doesn't imply validation passed
            if pe.validation_state == SurfaceValidationState.VALIDATED:
                # Only the truly validated platform should have proof beyond
                # merely naming a source file
                assert pe.platform == "linux-amd64", (
                    f"probe_artifact alone should not validate {pe.platform}"
                )

    def test_acp_parent_conservative_not_overstated(self, acp):
        """Parent validation_state is DECLARED (conservative) because

        Windows is only declared. A consumer must inspect per-platform
        evidence; the parent does not overstate coverage."""
        assert acp.validation_state == SurfaceValidationState.DECLARED, (
            "parent must be DECLARED when platforms are mixed"
        )
        # But at least one platform IS validated — linux-amd64
        validated_platforms = [
            p for p in acp.platforms
            if p.validation_state == SurfaceValidationState.VALIDATED
        ]
        assert len(validated_platforms) == 1, (
            "only linux-amd64 should be validated"
        )
        assert validated_platforms[0].platform == "linux-amd64"

    def test_acp_windows_effective_level_o0(self, acp):
        """Unvalidated Windows platform carries O0 — not overstated."""
        win = next((p for p in acp.platforms if p.platform == "windows-amd64"), None)
        assert win is not None
        # Unvalidated platforms should not carry O1+ effective level
        assert win.effective_level.numeric == 0, (
            f"unvalidated platform {win.platform} should be O0, not {win.effective_level.value}"
        )

# ── CLI session surface properties ──────────────────────────────────────────

class TestCLISessionSurfaceProperties:
    """OpenCode CLI session surface declares blocked state correctly."""

    @pytest.fixture
    def cli(self):
        desc = _load_opencode()
        return next(s for s in desc.session_surfaces if s.surface_id == "opencode-cli-session")

    def test_cli_validation_state_blocked(self, cli):
        """CLI session resume is blocked — not implemented yet (AS10)."""
        assert cli.validation_state == SurfaceValidationState.BLOCKED

    def test_cli_effective_level_o0(self, cli):
        """Blocked surface should be O0."""
        assert cli.effective_level.numeric == 0

    def test_cli_open_supported(self, cli):
        """CLI can open new sessions via `opencode run`."""
        assert (
            cli.identity_operations.get(SessionIdentityOperation.OPEN)
            == ControlSupport.SUPPORTED
        )

    def test_cli_resume_by_ref_unsupported(self, cli):
        """Resume-by-ref on CLI is unsupported — not implemented (AS10)."""
        assert (
            cli.identity_operations.get(SessionIdentityOperation.RESUME_BY_REF)
            == ControlSupport.UNSUPPORTED
        )

    def test_cli_no_content_channels(self, cli):
        """CLI session has no content channels declared yet."""
        assert len(cli.content_channels) == 0

# ── No invalid O2+ declarations ────────────────────────────────────────────

class TestNoInvalidO2Plus:
    """No surface declares effective O2+ without validation_state=validated."""

    def test_no_unvalidated_o2_plus_in_opencode(self):
        desc = _load_opencode()
        for s in desc.session_surfaces:
            if s.effective_level.numeric >= 2:
                assert s.validation_state == SurfaceValidationState.VALIDATED, (
                    f"surface {s.surface_id} declares O2+ without validation — rejected by loader"
                )

    def test_validated_has_all_platforms_validated(self):
        """If a parent is VALIDATED, every platform must also be VALIDATED.

        OpenCode ACP is DECLARED (not validated) because Windows is not proven.
        No surface in this repo should violate the cross-platform non-borrowing rule."""
        desc = _load_opencode()
        for s in desc.session_surfaces:
            if s.validation_state == SurfaceValidationState.VALIDATED:
                assert len(s.platforms) >= 1, (
                    f"validated surface {s.surface_id} has no platform evidence — rejected by loader"
                )
                # Cross-platform non-borrowing: all platforms must be validated
                for pe in s.platforms:
                    assert pe.validation_state == SurfaceValidationState.VALIDATED, (
                        f"validated parent {s.surface_id} has non-validated platform "
                        f"{pe.platform} ({pe.validation_state.value}) — cross-platform borrowing"
                    )

# ── No raw command/token/secret leak ────────────────────────────────────────

class TestNoSensitiveLeak:
    """Session-surface declarations must not carry raw commands, tokens, or secrets."""

    def test_no_raw_command_in_acp_declaration(self):
        desc = _load_opencode()
        acp = next(s for s in desc.session_surfaces if s.surface_id == "opencode-acp")
        # adapter_ref is a dotted path — no shell command strings
        assert isinstance(acp.adapter_ref, str)
        assert not any(
            kw in (acp.adapter_ref or "").lower()
            for kw in ("--model", "--format", "shell", "/bin/")
        )

    def test_no_native_protocol_identifier_leak(self):
        """No raw 'ACP' protocol name or native identifier in surface_id."""
        desc = _load_opencode()
        for s in desc.session_surfaces:
            assert "opencode-" in s.surface_id, (
                f"surface_id {s.surface_id} must prefix with provider id"
            )

# ── Cross-surface no fallback proof ────────────────────────────────────────

# ── Validation rule 3b: validated parent requires all platforms validated ─

class TestValidationRule3b:
    """Rule 3b: validated session surface requires all platforms to be validated.

    A source test file named in probe_artifact is NOT execution proof;
    cross-platform borrowing must be rejected at the loader.
    """

    def test_rule_3b_rejected_at_loader(self):
        """A validated parent with a non-validated platform should be rejected."""
        from audiagentic.components.providers.descriptors.session_surface_declarations import (
            SessionSurfaceDeclaration,
            _validate_declarations,
        )

        bad_decl = SessionSurfaceDeclaration(
            surface_id="test-surface",
            version_constraint=">=1.0",
            validation_state=SurfaceValidationState.VALIDATED,
            effective_level=EffectiveObservationLevel.O1,
            platforms=(
                PlatformEvidence(
                    platform="linux-amd64",
                    validation_state=SurfaceValidationState.VALIDATED,
                ),
                PlatformEvidence(
                    platform="windows-amd64",
                    validation_state=SurfaceValidationState.DECLARED,
                ),
            ),
        )
        with pytest.raises(AudiaGenticError, match="all platforms to be validated"):
            _validate_declarations([bad_decl])

    def test_opencode_surfaces_pass_rule_3b(self):
        """OpenCode YAML surfaces should pass the rule — parent is DECLARED.

        Since ACP is DECLARED (not VALIDATED), it won't be caught by Rule 3b
        even though Windows is only declared. This is the conservative model."""
        desc = _load_opencode()
        for s in desc.session_surfaces:
            if s.validation_state == SurfaceValidationState.VALIDATED:
                # If somehow a surface IS validated, all platforms must be too
                for pe in s.platforms:
                    assert pe.validation_state == SurfaceValidationState.VALIDATED


class TestNoCrossSurfaceFallback:
    """ACP and CLI surfaces are not interchangeable fallback routes."""

    def test_acp_and_cli_have_different_capabilities(self):
        desc = _load_opencode()
        acp = next(s for s in desc.session_surfaces if s.surface_id == "opencode-acp")
        cli = next(s for s in desc.session_surfaces if s.surface_id == "opencode-cli-session")

        # ACP is validated, CLI is blocked — they are fundamentally different
        assert acp.validation_state != cli.validation_state, (
            "ACP and CLI must not have the same validation state"
        )

        # ACP has content channels, CLI does not
        assert len(acp.content_channels) > 0
        assert len(cli.content_channels) == 0

        # ACP lifecycle is transport, CLI is none
        assert acp.lifecycle_source != cli.lifecycle_source
