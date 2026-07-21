"""AS27 inventory/conformance unit tests.

Tests the authoritative harness observability inventory, transport-observation
eligibility gate, and conformance enforcement. No new hooks or adapters — pure
inventory validation.
"""

from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    EffectiveObservationLevel,
    LifecycleSource,
    SurfaceValidationState,
)

# ---------------------------------------------------------------------------
# Inventory existence tests
# ---------------------------------------------------------------------------

class TestHarnessInventoryCompleteness:
    """Every known harness surface has exactly one explicit inventory entry."""

    def test_opencode_acp_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("opencode", "opencode-acp")
        assert fact is not None
        assert fact.provider_id == "opencode"
        assert fact.surface_id == "opencode-acp"

    def test_opencode_cli_session_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("opencode", "opencode-cli-session")
        assert fact is not None

    def test_codex_acp_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("codex", "codex-acp")
        assert fact is not None

    def test_codex_cli_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("codex", "codex-cli")
        assert fact is not None

    def test_claude_acp_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("claude", "claude-acp")
        assert fact is not None

    def test_claude_cli_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("claude", "claude-cli")
        assert fact is not None

    def test_gemini_acp_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("gemini", "gemini-acp")
        assert fact is not None

    def test_gemini_cli_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("gemini", "gemini-cli")
        assert fact is not None

    def test_copilot_acp_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("copilot", "copilot-acp")
        assert fact is not None

    def test_pi_rpc_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("pi", "pi-rpc")
        assert fact is not None

    def test_goose_acp_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("goose", "goose-acp")
        assert fact is not None

    def test_aider_cli_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("aider", "aider-cli")
        assert fact is not None

    def test_plandex_cli_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("plandex", "plandex-cli")
        assert fact is not None

    def test_roo_cli_exists(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("roo", "roo-cli")
        assert fact is not None

    def test_unknown_surface_returns_none(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("unknown", "unknown-surface")
        assert fact is None

# ---------------------------------------------------------------------------
# Eligibility gate tests — opencode-acp is the only eligible publisher
# ---------------------------------------------------------------------------

class TestTransportObservationEligibility:
    """Only opencode-acp satisfies the transport-observation eligibility gate."""

    def test_opencode_acp_is_eligible_on_linux(self):
        """Opencode ACP is eligible on linux-amd64 (one of its validated platforms)."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="linux-amd64",
        )

    def test_opencode_acp_not_eligible_on_windows(self):
        """Opencode ACP is NOT eligible on windows-amd64 — not in platform_evidence."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="windows-amd64",
        )

    def test_opencode_acp_not_eligible_on_darwin_arm64(self):
        """Opencode ACP is NOT eligible on darwin-arm64 — not in platform_evidence."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="darwin-arm64",
        )

    def test_opencode_acp_not_eligible_on_darwin_amd64(self):
        """Opencode ACP is NOT eligible on darwin-amd64 — not in platform_evidence."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="darwin-amd64",
        )

    def test_opencode_cli_session_not_eligible(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-cli-session"
        )

    def test_codex_acp_not_eligible(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher("codex", "codex-acp")

    def test_gemini_cli_not_eligible(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher("gemini", "gemini-cli")

    def test_copilot_acp_not_eligible(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher("copilot", "copilot-acp")

    def test_pi_rpc_not_eligible(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher("pi", "pi-rpc")

    def test_aider_cli_not_eligible(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher("aider", "aider-cli")

    def test_unknown_surface_not_eligible(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher(
            "unknown", "unknown-surface"
        )

    def test_eligible_list_linux_has_opencode_acp(self):
        """On linux-amd64, opencode-acp is the only eligible surface."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            list_eligible_transport_observation_surfaces,
        )
        eligible = list_eligible_transport_observation_surfaces(platform="linux-amd64")
        assert len(eligible) == 1
        assert ("opencode", "opencode-acp") in eligible

    def test_eligible_list_windows_empty(self):
        """On windows-amd64, no surface is eligible — opencode-acp not validated there."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            list_eligible_transport_observation_surfaces,
        )
        eligible = list_eligible_transport_observation_surfaces(platform="windows-amd64")
        assert len(eligible) == 0

    def test_eligible_list_darwin_arm64_empty(self):
        """On darwin-arm64, no surface is eligible — opencode-acp not validated there."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            list_eligible_transport_observation_surfaces,
        )
        eligible = list_eligible_transport_observation_surfaces(platform="darwin-arm64")
        assert len(eligible) == 0

# ---------------------------------------------------------------------------
# Conformance enforcement tests
# ---------------------------------------------------------------------------

class TestConformanceEnforcement:
    """Conformance rules prevent unvalidated surfaces from publishing."""

    def test_opencode_acp_conforms(self):
        """Opencode ACP passes conformance — validated with transport source."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            validate_harness_observability_conformance,
        )
        # Should not raise for the validated opencode-acp surface.
        validate_harness_observability_conformance(
            provider_id="opencode",
            surface_id="opencode-acp",
            lifecycle_source=LifecycleSource.TRANSPORT,
            effective_level=EffectiveObservationLevel.O1,
            validation_state=SurfaceValidationState.VALIDATED,
        )

    def test_unsupported_surface_claims_transport_raises(self):
        """An unsupported surface claiming transport observation raises VAL-HINV-001."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            validate_harness_observability_conformance,
        )
        with pytest.raises(AudiaGenticError) as exc_info:
            validate_harness_observability_conformance(
                provider_id="aider",
                surface_id="aider-cli",
                lifecycle_source=LifecycleSource.TRANSPORT,
                effective_level=EffectiveObservationLevel.O1,
                validation_state=SurfaceValidationState.DECLARED,
            )
        assert "VAL-HINV-001" in exc_info.value.code

    def test_probe_required_surface_claims_transport_raises(self):
        """A probe-required surface claiming transport observation raises VAL-HINV-001."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            validate_harness_observability_conformance,
        )
        with pytest.raises(AudiaGenticError) as exc_info:
            validate_harness_observability_conformance(
                provider_id="gemini",
                surface_id="gemini-acp",
                lifecycle_source=LifecycleSource.TRANSPORT,
                effective_level=EffectiveObservationLevel.O1,
                validation_state=SurfaceValidationState.DECLARED,
            )
        assert "VAL-HINV-001" in exc_info.value.code

    def test_non_validated_O2_claims_transport_raises(self):
        """Non-validated O2 claims transport observation raises VAL-HINV-001.

        gemini-cli is probe-required; claiming TRANSPORT on a non-validated
        surface hits rule 1 (unsupported lifecycle source) before rule 2
        (non-validated high level). The inventory is authoritative — if
        a surface is not validated, TRANSPORT is unsupported regardless of
        the declared effective_level."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            validate_harness_observability_conformance,
        )
        with pytest.raises(AudiaGenticError) as exc_info:
            validate_harness_observability_conformance(
                provider_id="gemini",
                surface_id="gemini-cli",
                lifecycle_source=LifecycleSource.TRANSPORT,
                effective_level=EffectiveObservationLevel.O2,
                validation_state=SurfaceValidationState.DECLARED,
            )
        # Rule 1 fires first: unsupported lifecycle source for non-validated surface
        assert "VAL-HINV-001" in exc_info.value.code

    def test_none_lifecycle_with_O1_raises(self):
        """A surface with no lifecycle source claiming O1 raises VAL-HINV-003."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            validate_harness_observability_conformance,
        )
        with pytest.raises(AudiaGenticError) as exc_info:
            validate_harness_observability_conformance(
                provider_id="opencode",
                surface_id="opencode-cli-session",
                lifecycle_source=LifecycleSource.NONE,
                effective_level=EffectiveObservationLevel.O1,
                validation_state=SurfaceValidationState.BLOCKED,
            )
        assert "VAL-HINV-003" in exc_info.value.code

    def test_unknown_surface_conforms_silently(self):
        """Unknown (provider_id, surface_id) pair passes silently — not in inventory."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            validate_harness_observability_conformance,
        )
        # Should not raise — unknown surfaces are just not in the matrix.
        validate_harness_observability_conformance(
            provider_id="unknown",
            surface_id="unknown-surface",
            lifecycle_source=LifecycleSource.NONE,
            effective_level=EffectiveObservationLevel.O0,
            validation_state=SurfaceValidationState.UNSUPPORTED,
        )

# ---------------------------------------------------------------------------
# Inventory data integrity tests
# ---------------------------------------------------------------------------

class TestInventoryDataIntegrity:
    """No duplicate (provider_id, surface_id) pairs; no inconsistent state."""

    def test_no_duplicate_surface_keys(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_all_harness_surface_facts,
        )
        facts = get_all_harness_surface_facts()
        keys = list(facts.keys())
        assert len(keys) == len(set(keys)), "Duplicate (provider_id, surface_id) found"

    def test_validated_surfaces_have_probe_anchor(self):
        """Every validated surface must have a probe anchor."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            CapabilityFactValidationState,
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if fact.validation_state == CapabilityFactValidationState.VALIDATED:
                assert fact.probe_anchor is not None, (
                    f"{pid}/{sid} is validated but has no probe_anchor"
                )

    def test_validated_surfaces_have_effective_level_at_least_O1(self):
        """Every validated surface must have effective_production_level >= O1."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            CapabilityFactValidationState,
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if fact.validation_state == CapabilityFactValidationState.VALIDATED:
                assert fact.effective_production_level.numeric >= 1, (
                    f"{pid}/{sid} is validated but effective level < O1"
                )

    def test_recipe_a_surfaces_have_transport_source(self):
        """Recipe A surfaces must have transport lifecycle source if validated."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            CapabilityFactValidationState,
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if fact.recipe == "A" and fact.validation_state == CapabilityFactValidationState.VALIDATED:
                assert fact.lifecycle_source == LifecycleSource.TRANSPORT, (
                    f"{pid}/{sid} is Recipe A validated but lifecycle_source != transport"
                )

    def test_recipe_d_surfaces_have_none_lifecycle_source(self):
        """Recipe D surfaces must have no lifecycle source."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if fact.recipe == "D":
                assert fact.lifecycle_source == LifecycleSource.NONE, (
                    f"{pid}/{sid} is Recipe D but has lifecycle_source != none"
                )

    def test_unsupported_surfaces_have_O0_effective_level(self):
        """Unsupported surfaces must have effective_production_level == O0."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            CapabilityFactValidationState,
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if fact.validation_state == CapabilityFactValidationState.UNSUPPORTED:
                assert fact.effective_production_level.numeric == 0, (
                    f"{pid}/{sid} is unsupported but effective level > O0"
                )

    def test_no_non_validated_O1_plus_transport(self):
        """No non-validated surface has transport lifecycle source with O1+."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            CapabilityFactValidationState,
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if (
                fact.lifecycle_source == LifecycleSource.TRANSPORT
                and fact.effective_production_level.numeric >= 1
            ):
                assert fact.validation_state == CapabilityFactValidationState.VALIDATED, (
                    f"{pid}/{sid} claims transport+O1+ but is not validated"
                )

    def test_supported_statuses_nonempty_only_when_validated(self):
        """Only validated surfaces may have non-empty supported_statuses."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            CapabilityFactValidationState,
            get_all_harness_surface_facts,
        )
        for (pid, sid), fact in get_all_harness_surface_facts().items():
            if fact.supported_statuses:
                assert fact.validation_state == CapabilityFactValidationState.VALIDATED, (
                    f"{pid}/{sid} has supported_statuses but is not validated"
                )

# ---------------------------------------------------------------------------
# Recipe A surface resolver integration test
# ---------------------------------------------------------------------------

class TestRecipeASurfaceResolverIntegration:
    """Resolver eligibility is derived from the platform-aware inventory."""

    def test_recipe_a_eligible_on_linux_from_inventory(self):
        """On linux-amd64, is_eligible matches list_eligible_transport_observation_surfaces."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
            list_eligible_transport_observation_surfaces,
        )

        eligible_list = list_eligible_transport_observation_surfaces(platform="linux-amd64")
        for pid, sid in eligible_list:
            assert is_eligible_transport_observation_publisher(
                pid, sid, platform="linux-amd64",
            ), f"{pid}/{sid} in list but not eligible"

    def test_recipe_a_opencode_acp_eligible_on_linux(self):
        """opencode-acp is eligible on linux-amd64."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="linux-amd64",
        )

    def test_recipe_a_excludes_non_validated_on_linux(self):
        """Non-validated surfaces are NOT eligible on linux-amd64 either."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        assert not is_eligible_transport_observation_publisher(
            "codex", "codex-acp", platform="linux-amd64",
        )
        assert not is_eligible_transport_observation_publisher(
            "gemini", "gemini-acp", platform="linux-amd64",
        )
        assert not is_eligible_transport_observation_publisher(
            "copilot", "copilot-acp", platform="linux-amd64",
        )

# ---------------------------------------------------------------------------
# Platform-neutral eligibility conformance tests
# ---------------------------------------------------------------------------

class TestPlatformNeutralEligibility:
    """Platform support alone is not status evidence; AS29 surface validation is.

    Conformance: opencode-acp's platform_evidence comes from the descriptor,
    not inventory guesswork. The eligibility gate checks that the requested
    platform appears in validated platform_evidence — empty means no restriction.

    Status publication (AS19) is eligible only when the configured AS29 surface
    carries exact launch/version/correlation evidence. Platform support alone
    does not prove status observability.
    """

    def test_platform_evidence_comes_from_descriptor(self):
        """Platform evidence for opencode-acp derives from descriptor, not guesswork.

        Only linux-amd64 is proven — do not claim validation beyond the
        validated platform (AS27: do not claim validation beyond proven
        platform/version).
        """
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("opencode", "opencode-acp")
        assert fact is not None
        # platform_evidence contains only the proven platform
        assert len(fact.platform_evidence) >= 1
        assert "linux-amd64" in fact.platform_evidence
        # Do NOT claim cross-platform validation beyond what is proven
        assert "windows-amd64" not in fact.platform_evidence
        assert "darwin-arm64" not in fact.platform_evidence

    def test_non_eligible_surface_has_empty_platform_evidence(self):
        """Non-validated surfaces have empty platform_evidence — no OS restriction needed."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
        fact = get_harness_surface_capability_fact("codex", "codex-acp")
        assert fact is not None
        assert fact.platform_evidence == ()

    def test_eligibility_gate_requires_validation_not_just_platform(self):
        """Platform match alone does not grant eligibility — validation_state must be VALIDATED."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        # codex-acp has no platform_evidence (empty = no restriction)
        # but it is NOT validated, so it is not eligible.
        assert not is_eligible_transport_observation_publisher(
            "codex", "codex-acp", platform="linux-amd64",
        )

    def test_eligibility_gate_requires_effective_level(self):
        """Validation + platform match is not enough — effective_production_level must be >= O1."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        # opencode-cli-session is blocked, O0 — never eligible regardless of platform.
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-cli-session", platform="linux-amd64",
        )

    def test_cross_platform_eligible_set_consistent(self):
        """Eligible set is the same on all validated platforms for opencode-acp."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            list_eligible_transport_observation_surfaces,
        )
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )

        fact = get_harness_surface_capability_fact("opencode", "opencode-acp")
        assert fact is not None
        for platform in fact.platform_evidence:
            eligible = list_eligible_transport_observation_surfaces(platform=platform)
            assert ("opencode", "opencode-acp") in eligible, (
                f"opencode-acp missing from eligible set on {platform}"
            )

    def test_unsupported_platform_still_rejects(self):
        """A surface with non-empty platform_evidence rejects platforms not listed."""
        from audiagentic.components.providers.services.harness_observability_inventory import (
            is_eligible_transport_observation_publisher,
        )
        # opencode-acp does not list linux-386 — reject it.
        assert not is_eligible_transport_observation_publisher(
            "opencode", "opencode-acp", platform="linux-386",
        )

# ---------------------------------------------------------------------------
# Markdown rendering test
# ---------------------------------------------------------------------------

class TestMarkdownRendering:
    """Inventory renders as deterministic markdown."""

    def test_markdown_has_header(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            render_harness_inventory_markdown,
        )
        rendered = render_harness_inventory_markdown()
        assert "# AS27 Harness Observability Inventory" in rendered

    def test_markdown_contains_opencode_acp(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            render_harness_inventory_markdown,
        )
        rendered = render_harness_inventory_markdown()
        assert "opencode-acp" in rendered

    def test_markdown_contains_table_rows(self):
        from audiagentic.components.providers.services.harness_observability_inventory import (
            render_harness_inventory_markdown,
        )
        rendered = render_harness_inventory_markdown()
        # Each row starts with "| "
        rows = [line for line in rendered.split("\n") if line.startswith("|")]
        # Header + separator + data rows
        assert len(rows) >= 10
