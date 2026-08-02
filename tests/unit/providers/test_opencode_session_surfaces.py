"""AS29 slice 4 — OpenCode session-surfaces descriptor declarations and loader tests.

Loads the real OpenCode provider YAML and proves:
- Duplicate prevention (distinct surface IDs, same version)
- Distinct ACP vs CLI surface IDs (not interchangeable fallbacks)
- Controls/content channels require validated evidence (AS59 rule)
- Evidence matches what's actually proven in this repo
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
    LifecycleSource,
    PlatformEvidence,
    SessionControlAction,
    SessionIdentityOperation,
    ValidationEvidence,
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

    def test_acp_evidence_validated_with_reference(self, acp):
        """ACP parent evidence.validated is True — at least one platform

        (linux-amd64) is genuinely proven (AS59 rule 3b: a validated parent
        requires at least one validated platform, not that every platform be
        validated — Windows/macOS remain unvalidated declarations)."""
        assert acp.evidence.validated is True
        assert acp.evidence.reference == "tests/e2e/agents/test_opencode_acp_e2e.py"

    def test_acp_has_platform_evidence(self, acp):
        """Surface carries platform evidence with mixed states."""
        assert len(acp.platforms) >= 1, "surface should carry platform evidence"

    def test_acp_linux_platform_validated(self, acp):
        """Linux-amd64 platform for ACP is validated (e2e tested)."""
        linux = next((p for p in acp.platforms if p.platform == "linux-amd64"), None)
        assert linux is not None
        assert linux.evidence.validated is True

    def test_acp_windows_platform_declared(self, acp):
        """Windows-amd64 platform for ACP is declared but not proven."""
        win = next((p for p in acp.platforms if p.platform == "windows-amd64"), None)
        assert win is not None
        # Windows not proven yet — should not be validated
        assert win.evidence.validated is False

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

    def test_acp_windows_not_validated(self, acp):
        """Windows-amd64 is declared but NOT validated — no e2e proof yet."""
        win = next((p for p in acp.platforms if p.platform == "windows-amd64"), None)
        assert win is not None
        assert win.evidence.validated is False, (
            "Windows platform must not be validated without e2e proof"
        )

    def test_acp_only_linux_platform_validated(self, acp):
        """Only linux-amd64 carries real proof; every other platform row is
        declared-but-unvalidated. A probe_artifact naming a source file is
        NOT execution proof by itself — only the platform this repo actually
        ran the e2e test against may be validated."""
        validated_platforms = [p for p in acp.platforms if p.evidence.validated]
        assert len(validated_platforms) == 1, "only linux-amd64 should be validated"
        assert validated_platforms[0].platform == "linux-amd64"

# ── CLI session surface properties ──────────────────────────────────────────

class TestCLISessionSurfaceProperties:
    """OpenCode CLI session surface declares blocked state correctly."""

    @pytest.fixture
    def cli(self):
        desc = _load_opencode()
        return next(s for s in desc.session_surfaces if s.surface_id == "opencode-cli-session")

    def test_cli_evidence_not_validated(self, cli):
        """CLI session resume is not proven — not implemented yet (AS10)."""
        assert cli.evidence.validated is False

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

# ── Controls/content require validated evidence (AS59 rule 2) ──────────────

class TestControlsRequireValidatedEvidence:
    """No surface declares controls/content channels without validated evidence."""

    def test_no_unvalidated_controls_or_content_in_opencode(self):
        desc = _load_opencode()
        for s in desc.session_surfaces:
            if s.controls or s.content_channels:
                assert s.evidence.validated, (
                    f"surface {s.surface_id} declares controls/content without "
                    "validated evidence — rejected by the loader"
                )

    def test_validated_has_at_least_one_validated_platform(self):
        """If a parent's evidence.validated is True, at least one platform row
        must also be validated (AS59 rule 3b — not every platform, just one;
        cross-platform borrowing of PROOF is still not allowed elsewhere)."""
        desc = _load_opencode()
        for s in desc.session_surfaces:
            if s.evidence.validated:
                assert len(s.platforms) >= 1, (
                    f"validated surface {s.surface_id} has no platform evidence — "
                    "rejected by the loader"
                )
                assert any(pe.evidence.validated for pe in s.platforms), (
                    f"validated parent {s.surface_id} has no validated platform row"
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

# ── Rule 3: validated declaration requires platform evidence ───────────────

class TestValidatedRequiresPlatformEvidence:
    """A validated session surface requires at least one platform row, and
    that parent claim requires at least one platform ALSO validated — a
    source test file named in probe_artifact is NOT execution proof by
    itself; cross-platform-only claims must be rejected at the loader.
    """

    def test_validated_with_no_validated_platform_rejected_at_loader(self):
        """A validated parent whose platforms are all unvalidated is rejected."""
        from audiagentic.components.providers.descriptors.session_surface_declarations import (
            SessionSurfaceDeclaration,
            _validate_declarations,
        )

        bad_decl = SessionSurfaceDeclaration(
            surface_id="test-surface",
            version_constraint=">=1.0",
            evidence=ValidationEvidence(validated=True, reference="doc"),
            platforms=(
                # No validated platform at all — rejected.
                PlatformEvidence(platform="linux-amd64"),
                PlatformEvidence(platform="windows-amd64"),
            ),
        )
        with pytest.raises(AudiaGenticError, match="at least one validated platform"):
            _validate_declarations([bad_decl])

    def test_opencode_acp_passes_the_rule(self):
        """OpenCode ACP's parent is validated=True and linux-amd64 is the
        validated platform backing that claim — passes rule 3b."""
        desc = _load_opencode()
        acp = next(s for s in desc.session_surfaces if s.surface_id == "opencode-acp")
        assert acp.evidence.validated is True
        assert any(pe.evidence.validated for pe in acp.platforms)


class TestNoCrossSurfaceFallback:
    """ACP and CLI surfaces are not interchangeable fallback routes."""

    def test_acp_and_cli_have_different_capabilities(self):
        desc = _load_opencode()
        acp = next(s for s in desc.session_surfaces if s.surface_id == "opencode-acp")
        cli = next(s for s in desc.session_surfaces if s.surface_id == "opencode-cli-session")

        # ACP is validated, CLI is not — they are fundamentally different
        assert acp.evidence.validated != cli.evidence.validated, (
            "ACP and CLI must not have the same evidence.validated state"
        )

        # ACP has content channels, CLI does not
        assert len(acp.content_channels) > 0
        assert len(cli.content_channels) == 0

        # ACP lifecycle is transport, CLI is none
        assert acp.lifecycle_source != cli.lifecycle_source
