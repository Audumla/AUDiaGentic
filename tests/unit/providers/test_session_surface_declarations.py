"""AS29 stage 2 — provider descriptor session-surface declaration loading and validation.

Tests default compatibility, one valid surface, every rejection case, and no
accidental descriptor import from agents.
"""

from __future__ import annotations

import pytest

from audiagentic.components.providers.descriptors.base import ProviderDescriptor
from audiagentic.components.providers.descriptors.loader import (
    PROVIDER_SPEC,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    ContentChannelId,
    ControlSupport,
    LifecycleInstallation,
    ResolvedSessionSurface,
    SessionControlAction,
    SessionIdentityOperation,
    SessionOwnershipMode,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _valid_surface_data(**overrides) -> dict:
    """Return a valid YAML-style surface entry dict.

    Carries controls, so evidence.validated must be True (declarations rule 2).
    """
    data = {
        "surface_id": "acp",
        "version_constraint": ">=1.0",
        "identity_operations": {
            "open": "supported",
            "attach-existing": "unsupported",
        },
        "ownership_modes": ["owned"],
        "controls": {"cancel-turn": "supported"},
        "lifecycle_source": "transport",
        "lifecycle_installation": "none",
        "evidence": {"validated": True, "reference": "tests/fixtures/acp-probe.md"},
        "platforms": [
            {
                "platform": "linux-amd64",
                "evidence": {"validated": True, "reference": "tests/fixtures/acp-probe.md"},
            },
        ],
        "adapter_ref": None,
    }
    data.update(overrides)
    return data


def _min_valid_descriptor_data() -> dict:
    """Minimal valid ProviderDescriptor YAML data."""
    return {
        "provider_id": "test-provider",
        "display_name": "Test Provider",
        "execution_isolation_tier": "no-isolation",
    }


# ── Default compatibility (backward compat) ────────────────────────────────


class TestDefaultCompatibility:
    """Providers without session_surfaces continue to work."""

    def test_empty_session_surfaces_default(self):
        """session_surfaces defaults to empty tuple when absent in YAML."""
        data = _min_valid_descriptor_data()
        descriptor = PROVIDER_SPEC.build(data)
        assert descriptor.session_surfaces == ()

    def test_existing_providers_load_without_session_surfaces_field(self):
        """PROVIDER_SPEC loads descriptors without session_surfaces key."""
        from audiagentic.components.providers.descriptors.loader import (
            get_providers_config_dir,
            load_providers_from_directory,
        )

        providers = load_providers_from_directory(get_providers_config_dir())
        assert len(providers) > 0
        for desc in providers.values():
            # All existing providers should have empty tuple
            assert isinstance(desc.session_surfaces, tuple)

    def test_no_session_surface_in_provider_descriptor_fields_breaks_existing(self):
        """The new field does not break ProviderDescriptor construction."""
        desc = ProviderDescriptor(
            provider_id="test",
            display_name="Test",
            execution_isolation_tier="no-isolation",
        )
        assert desc.session_surfaces == ()


# ── One valid surface ──────────────────────────────────────────────────────


class TestValidSurface:
    """A valid session-surface declaration loads and validates."""

    def test_single_valid_surface(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [_valid_surface_data()]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1
        decl = descriptor.session_surfaces[0]
        assert decl.surface_id == "acp"
        assert decl.version_constraint == ">=1.0"

    def test_valid_surface_with_validation_and_platforms(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                evidence={"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                platforms=[
                    {
                        "platform": "linux-amd64",
                        "evidence": {"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                    },
                ],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert decl.evidence.validated is True
        assert decl.evidence.reference == "tests/fixtures/acp-probe.md"
        assert len(decl.platforms) == 1

    def test_valid_surface_with_content_channels(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                content_channels=[
                    {"channel": "assistant-text", "max_bytes": 65536, "max_events": 100},
                ],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert len(decl.content_channels) == 1
        ch = decl.content_channels[0]
        assert ch.channel == ContentChannelId.ASSISTANT_TEXT
        assert ch.max_bytes == 65536

    def test_valid_surface_with_managed_hook_and_adapter_ref(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-hook",
                adapter_ref="audiagentic.components.providers.adapters.test.hook:install",
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert decl.lifecycle_installation == LifecycleInstallation.MANAGED_HOOK
        assert decl.adapter_ref == "audiagentic.components.providers.adapters.test.hook:install"

    def test_valid_surface_with_managed_plugin_and_adapter_ref(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-plugin",
                adapter_ref="audiagentic.components.providers.adapters.test.plugin:install",
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert decl.lifecycle_installation == LifecycleInstallation.MANAGED_PLUGIN

    def test_valid_surface_all_identity_operations(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                identity_operations={
                    "open": "supported",
                    "attach-existing": "supported",
                    "resume-by-ref": "unsupported",
                    "discover": "supported",
                },
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert SessionIdentityOperation.OPEN in decl.identity_operations
        assert decl.identity_operations[SessionIdentityOperation.OPEN] == ControlSupport.SUPPORTED

    def test_valid_surface_ownership_modes(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                ownership_modes=["owned", "adopted", "external"],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert SessionOwnershipMode.OWNED in decl.ownership_modes
        assert SessionOwnershipMode.EXTERNAL in decl.ownership_modes

    def test_valid_surface_all_control_actions(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                controls={
                    "cancel-turn": "supported",
                    "interrupt-turn": "unsupported",
                    "steer-turn": "supported",
                    "respond-permission": "unsupported",
                    "close-session": "supported",
                },
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert SessionControlAction.CANCEL_TURN in decl.controls

    def test_adapter_ref_stays_string_not_resolved(self):
        """adapter_ref is kept as a raw string, not resolved to a callable."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-hook",
                adapter_ref="audiagentic.components.providers.adapters.test.hook:install",
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        # adapter_ref is a string, NOT a callable
        assert isinstance(decl.adapter_ref, str)
        assert not callable(decl.adapter_ref)

    def test_adapter_ref_not_in_resolved_session_surface(self):
        """ResolvedSessionSurface has no adapter_ref field — it is foundation type."""
        import dataclasses

        surface_fields = {f.name for f in dataclasses.fields(ResolvedSessionSurface)}
        assert "adapter_ref" not in surface_fields


# ── Rejection: duplicate (surface_id, version_constraint) ───────────────────


class TestRejectDuplicateKey:
    """Duplicate (surface_id, version_constraint) is rejected."""

    def test_duplicate_rejected(self):
        data = _min_valid_descriptor_data()
        base = _valid_surface_data()
        data["session_surfaces"] = [base, base]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_different_version_constraint_ok(self):
        """Same surface_id but different version_constraint is allowed."""
        data = _min_valid_descriptor_data()
        s1 = _valid_surface_data(version_constraint=">=1.0")
        s2 = _valid_surface_data(version_constraint=">=2.0")
        data["session_surfaces"] = [s1, s2]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 2

    def test_different_surface_id_ok(self):
        """Different surface_id with same version_constraint is allowed."""
        data = _min_valid_descriptor_data()
        s1 = _valid_surface_data(surface_id="acp")
        s2 = _valid_surface_data(surface_id="mcp", version_constraint=">=1.0")
        data["session_surfaces"] = [s1, s2]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 2


# ── Rejection: controls/content channels without validated evidence ────────


class TestRejectUnvalidatedControlsOrContent:
    """Controls or content channels require evidence.validated=True (AS59)."""

    def test_controls_without_validated_evidence_rejected(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                controls={"cancel-turn": "supported"},
                evidence={"validated": False, "reference": ""},
                platforms=[],
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_content_channels_without_validated_evidence_rejected(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                controls={},
                content_channels=[{"channel": "assistant-text", "max_bytes": 1024}],
                evidence={"validated": False, "reference": ""},
                platforms=[],
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_no_controls_no_content_unvalidated_allowed(self):
        """A bare open/close-only declaration needs no validated evidence."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                controls={},
                content_channels=[],
                evidence={"validated": False, "reference": ""},
                platforms=[],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1

    def test_controls_with_validated_evidence_allowed(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                controls={"cancel-turn": "supported"},
                evidence={"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                platforms=[
                    {
                        "platform": "linux-amd64",
                        "evidence": {"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                    },
                ],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1


# ── Rejection: validated with no platform evidence ─────────────────────────


class TestRejectValidatedNoEvidence:
    """Validated declaration with no platform evidence is rejected."""

    def test_validated_no_platforms_rejected(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                evidence={"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                platforms=[],
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_validated_with_one_platform_allowed(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                evidence={"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                platforms=[
                    {
                        "platform": "windows-amd64",
                        "evidence": {"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                    }
                ],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1

    def test_validated_with_multiple_platforms_allowed(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                evidence={"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                platforms=[
                    {
                        "platform": "linux-amd64",
                        "evidence": {"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                    },
                    {
                        "platform": "windows-amd64",
                        "evidence": {"validated": True, "reference": "tests/fixtures/acp-probe.md"},
                    },
                ],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        decl = descriptor.session_surfaces[0]
        assert len(decl.platforms) == 2


# ── Rejection: content channel with zero/absent bounds ─────────────────────


class TestRejectZeroBoundContentChannel:
    """Content channel with zero/absent byte AND event bound is rejected."""

    def test_zero_both_bounds_rejected(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                content_channels=[
                    {"channel": "assistant-text", "max_bytes": 0, "max_events": 0},
                ],
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_absent_bounds_default_zero_rejected(self):
        """No max_bytes/max_events → defaults to 0/0 → rejected."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                content_channels=[
                    {"channel": "assistant-text"},
                ],
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_nonzero_bytes_ok(self):
        """Nonzero max_bytes is allowed even if max_events is 0."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                content_channels=[
                    {"channel": "assistant-text", "max_bytes": 1024, "max_events": 0},
                ],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1

    def test_nonzero_events_ok(self):
        """Nonzero max_events is allowed even if max_bytes is 0."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                content_channels=[
                    {"channel": "assistant-text", "max_bytes": 0, "max_events": 50},
                ],
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1


# ── Rejection: managed-hook/plugin without adapter_ref ─────────────────────


class TestRejectManagedHookPluginNoAdapterRef:
    """Managed-hook/plugin lifecycle without nonempty adapter_ref is rejected."""

    def test_managed_hook_no_adapter_ref_rejected(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-hook",
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_managed_plugin_no_adapter_ref_rejected(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-plugin",
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_managed_hook_with_adapter_ref_allowed(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-hook",
                adapter_ref="audiagentic.components.providers.adapters.test.hook:install",
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1

    def test_managed_plugin_with_adapter_ref_allowed(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-plugin",
                adapter_ref="audiagentic.components.providers.adapters.test.plugin:install",
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1

    def test_none_adapter_ref_still_rejected(self):
        """Explicit null/None adapter_ref for managed-hook is rejected."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-hook",
                adapter_ref=None,
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_empty_string_adapter_ref_rejected(self):
        """Empty string adapter_ref for managed-hook is rejected."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="managed-hook",
                adapter_ref="",
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_none_installation_no_adapter_ok(self):
        """none lifecycle installation does not require adapter_ref."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="none",
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1

    def test_transport_source_no_adapter_ok(self):
        """transport lifecycle source with none installation doesn't need adapter_ref."""
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_source="transport",
                lifecycle_installation="none",
            ),
        ]
        descriptor = PROVIDER_SPEC.build(data)
        assert len(descriptor.session_surfaces) == 1


# ── Rejection: invalid enum domains ────────────────────────────────────────


class TestRejectInvalidEnumDomains:
    """Invalid enum values in identity_operations and controls are rejected."""

    def test_invalid_identity_operation_key(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                identity_operations={
                    "invalid-op": "supported",
                },
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_control_support_value_in_identity(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                identity_operations={
                    "open": "maybe",
                },
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_control_action_key(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                controls={
                    "invalid-action": "supported",
                },
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_control_support_value_in_controls(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                controls={
                    "cancel-turn": "maybe",
                },
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_ownership_mode(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                ownership_modes=["owned", "invalid-mode"],
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_lifecycle_source(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_source="invalid-source",
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_lifecycle_installation(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                lifecycle_installation="invalid-installation",
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_content_channel_id(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                content_channels=[
                    {"channel": "invalid-channel", "max_bytes": 1024},
                ],
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_validation_state(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                validation_state="invalid-state",
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_invalid_effective_level(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            _valid_surface_data(
                effective_level="O5",
            ),
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)


# ── Rejection: structural errors ───────────────────────────────────────────


class TestRejectStructuralErrors:
    """Structural validation errors are rejected."""

    def test_missing_surface_id(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            {"version_constraint": ">=1.0"},
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_missing_version_constraint(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            {"surface_id": "acp"},
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_session_surfaces_not_a_list(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = "not-a-list"
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_entry_not_a_mapping(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = ["not-a-mapping"]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)

    def test_unknown_fields_rejected(self):
        data = _min_valid_descriptor_data()
        data["session_surfaces"] = [
            {**_valid_surface_data(), "unknown_field": "value"},
        ]
        with pytest.raises(AudiaGenticError, match="VAL-PCAP-011"):
            PROVIDER_SPEC.build(data)


# ── Type compatibility: _parse_enum accepts set and frozenset ──────────────


class TestParseEnumTypeCompatibility:
    """_parse_enum's allowed_values parameter accepts both set[str] and frozenset[str]."""

    def test_parse_enum_accepts_plain_set(self):
        from audiagentic.components.providers.descriptors.session_surface_declarations import (
            _CONTROL_SUPPORT_MAP,
            _parse_enum,
        )

        allowed: set[str] = {v.value for v in ControlSupport}
        result = _parse_enum("supported", allowed, _CONTROL_SUPPORT_MAP, "control")
        assert result is ControlSupport.SUPPORTED

    def test_parse_enum_accepts_frozenset(self):
        from audiagentic.components.providers.descriptors.session_surface_declarations import (
            _CONTROL_SUPPORT_MAP,
            _parse_enum,
        )

        allowed: frozenset[str] = frozenset({v.value for v in ControlSupport})
        result = _parse_enum("supported", allowed, _CONTROL_SUPPORT_MAP, "control")
        assert result is ControlSupport.SUPPORTED


# ── No accidental descriptor import from agents ────────────────────────────


class TestNoAccidentalDescriptorImportFromAgents:
    """The session_surface_declarations module must not import agent components."""

    def test_no_agent_import_in_session_surface_declarations(self):
        """session_surface_declarations.py must not import from agents."""
        mod = __import__(
            "audiagentic.components.providers.descriptors.session_surface_declarations",
            fromlist=["SessionSurfaceDeclaration"],
        )
        import inspect

        source_code = inspect.getsource(mod)
        for line in source_code.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for bad in (
                "from audiagentic.components.agents",
                "import audiagentic.components.agents",
                "from audiagentic.foundation.transports.acp import",
                # adapter_ref is descriptor-local string, never imported
            ):
                if bad in stripped:
                    pytest.fail(
                        f"session_surface_declarations.py must not import agents/ACP — found: {stripped!r}"
                    )

    def test_session_surface_declaration_has_adapter_ref_not_callable(self):
        """SessionSurfaceDeclaration carries adapter_ref as str, not a callable."""
        import dataclasses

        from audiagentic.components.providers.descriptors.session_surface_declarations import (
            SessionSurfaceDeclaration,
        )

        field_types = {f.name: f.type for f in dataclasses.fields(SessionSurfaceDeclaration)}
        assert "adapter_ref" in field_types
        # The type annotation is str | None — not Callable

    def test_resolved_session_surface_has_no_adapter_ref(self):
        """Foundation ResolvedSessionSurface must never have adapter_ref."""
        import dataclasses

        surface_fields = {f.name for f in dataclasses.fields(ResolvedSessionSurface)}
        assert "adapter_ref" not in surface_fields, (
            "ResolvedSessionSurface must not carry descriptor-local adapter_ref"
        )
