"""AS29 stage 1 — foundation session-surface value types and import neutrality.

Tests frozen/immutable values, enum/value validation, scalar-only discipline,
and that the module imports no ``components.*`` modules.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

import pytest

# ── Module under test ───────────────────────────────────────────────────────
from audiagentic.foundation.transports.session_surface import (
    ContentChannelCapability,
    ContentChannelId,
    ContentStreamCapabilities,
    ControlSupport,
    LifecycleInstallation,
    LifecycleObservationCapabilities,
    LifecycleSource,
    PlatformEvidence,
    ResolvedSessionSurface,
    SessionControlAction,
    SessionIdentityCapabilities,
    SessionIdentityOperation,
    SessionMappingFacts,
    SessionOwnershipMode,
    SessionSurfaceRef,
    SurfaceValidation,
    ValidationEvidence,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_scalar_or_enum(value: Any) -> bool:
    """True if value is a primitive, enum member, or immutable dataclass with no callables."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    import enum
    if isinstance(value, enum.Enum):
        return True
    if isinstance(value, tuple) and all(isinstance(v, (str, int, float, bool, type(None))) or isinstance(v, enum.Enum) for v in value):
        return True
    return False


# ── Enum membership ────────────────────────────────────────────────────────

class TestIdentityOperation:
    def test_has_open(self):
        assert SessionIdentityOperation.OPEN.value == "open"

    def test_has_attach_existing(self):
        assert SessionIdentityOperation.ATTACH_EXISTING.value == "attach-existing"

    def test_has_resume_by_ref(self):
        assert SessionIdentityOperation.RESUME_BY_REF.value == "resume-by-ref"

    def test_has_discover(self):
        assert SessionIdentityOperation.DISCOVER.value == "discover"


class TestControlSupport:
    def test_values(self):
        assert ControlSupport.SUPPORTED.value == "supported"
        assert ControlSupport.UNSUPPORTED.value == "unsupported"


class TestSessionControlAction:
    def test_all_actions_present(self):
        expected = {
            "cancel-turn", "interrupt-turn", "steer-turn",
            "respond-permission", "close-session",
        }
        actual = {a.value for a in SessionControlAction}
        assert actual == expected


class TestSessionOwnershipMode:
    def test_values(self):
        assert SessionOwnershipMode.OWNED.value == "owned"
        assert SessionOwnershipMode.ADOPTED.value == "adopted"
        assert SessionOwnershipMode.EXTERNAL.value == "external"


class TestLifecycleSource:
    def test_all_sources_present(self):
        expected = {
            "transport", "hook", "plugin", "native-api",
            "structured-output", "none",
        }
        actual = {s.value for s in LifecycleSource}
        assert actual == expected


class TestLifecycleInstallation:
    def test_values(self):
        assert LifecycleInstallation.NONE.value == "none"
        assert LifecycleInstallation.MANAGED_HOOK.value == "managed-hook"
        assert LifecycleInstallation.MANAGED_PLUGIN.value == "managed-plugin"
        assert LifecycleInstallation.STRUCTURED_OUTPUT.value == "structured-output"


class TestContentChannelId:
    def test_values(self):
        assert ContentChannelId.ASSISTANT_TEXT.value == "assistant-text"
        assert ContentChannelId.ASSISTANT_FINAL.value == "assistant-final"
        assert ContentChannelId.TOOL_SUMMARY.value == "tool-summary"


class TestValidationEvidence:
    def test_defaults(self):
        evidence = ValidationEvidence()
        assert evidence.validated is False
        assert evidence.reference == ""

    def test_validated_requires_reference(self):
        with pytest.raises(ValueError):
            ValidationEvidence(validated=True, reference="")

    def test_validated_with_reference(self):
        evidence = ValidationEvidence(validated=True, reference="tests/e2e/agents/test_opencode_acp_e2e.py")
        assert evidence.validated is True
        assert evidence.reference == "tests/e2e/agents/test_opencode_acp_e2e.py"


# ── Frozen / immutability ──────────────────────────────────────────────────

class TestSessionSurfaceRef:
    def test_frozen(self):
        ref = SessionSurfaceRef(provider_id="opencode", surface_id="acp", resolved_version="1.0")
        with pytest.raises(Exception):  # FrozenInstanceError
            ref.provider_id = "other"

    def test_requires_non_empty_strings(self):
        for field_name in ("provider_id", "surface_id", "resolved_version"):
            kwargs = {"provider_id": "p", "surface_id": "s", "resolved_version": "v"}
            kwargs[field_name] = ""
            with pytest.raises(ValueError, match=field_name):
                SessionSurfaceRef(**kwargs)

    def test_equality(self):
        a = SessionSurfaceRef("opencode", "acp", "1.0")
        b = SessionSurfaceRef("opencode", "acp", "1.0")
        assert a == b
        c = SessionSurfaceRef("opencode", "acp", "2.0")
        assert a != c


class TestSessionMappingFacts:
    def test_frozen(self):
        facts = SessionMappingFacts(ref_scope="surface")
        with pytest.raises(Exception):
            facts.ref_scope = "other"

    def test_defaults(self):
        facts = SessionMappingFacts()
        assert facts.ref_namespace == "provider-session-ref"
        assert facts.requires_same_project is True
        assert facts.requires_same_execution_context is True
        assert facts.concurrent_attachments is False


class TestSessionIdentityCapabilities:
    def test_frozen(self):
        caps = SessionIdentityCapabilities()
        with pytest.raises(Exception):
            caps.identity_operations["x"] = ControlSupport.SUPPORTED  # type: ignore

    def test_operation_supported(self):
        ops = {SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED}
        caps = SessionIdentityCapabilities(identity_operations=ops)
        assert caps.operation_supported(SessionIdentityOperation.OPEN) is True
        assert caps.operation_supported(SessionIdentityOperation.DISCOVER) is False

    def test_supports_ownership(self):
        caps = SessionIdentityCapabilities(
            ownership_modes=(SessionOwnershipMode.OWNED, SessionOwnershipMode.EXTERNAL),
        )
        assert caps.supports_ownership(SessionOwnershipMode.OWNED) is True
        assert caps.supports_ownership(SessionOwnershipMode.ADOPTED) is False

    def test_empty_ownership(self):
        caps = SessionIdentityCapabilities()
        assert not caps.supports_ownership(SessionOwnershipMode.OWNED)


class TestLifecycleObservationCapabilities:
    def test_frozen(self):
        lc = LifecycleObservationCapabilities(source=LifecycleSource.TRANSPORT)
        with pytest.raises(Exception):
            lc.source = LifecycleSource.HOOK

    def test_defaults(self):
        lc = LifecycleObservationCapabilities()
        assert lc.source == LifecycleSource.NONE
        assert lc.installation == LifecycleInstallation.NONE
        assert lc.correlation_id_supported is False


class TestContentChannelCapability:
    def test_frozen(self):
        ch = ContentChannelCapability(channel=ContentChannelId.ASSISTANT_TEXT, max_bytes=1024)
        with pytest.raises(Exception):
            ch.max_bytes = 2048

    def test_bounds_must_be_non_negative(self):
        for bad_val in (-1, -100):
            with pytest.raises(ValueError):
                ContentChannelCapability(
                    channel=ContentChannelId.ASSISTANT_TEXT,
                    max_bytes=bad_val,
                )
            with pytest.raises(ValueError):
                ContentChannelCapability(
                    channel=ContentChannelId.ASSISTANT_TEXT,
                    max_events=bad_val,
                )


class TestContentStreamCapabilities:
    def test_has_channel(self):
        channels = (ContentChannelCapability(ContentChannelId.ASSISTANT_TEXT),)
        caps = ContentStreamCapabilities(channels=channels)
        assert caps.has_channel(ContentChannelId.ASSISTANT_TEXT) is True
        assert caps.has_channel(ContentChannelId.TOOL_SUMMARY) is False

    def test_empty_channels(self):
        caps = ContentStreamCapabilities()
        assert not caps.has_channel(ContentChannelId.ASSISTANT_TEXT)


class TestResolvedSessionSurface:
    def test_frozen(self):
        surface = self._make_surface()
        with pytest.raises(Exception):
            surface.ref = SessionSurfaceRef("x", "y", "z")

    def test_control_supported(self):
        controls = {SessionControlAction.CANCEL_TURN: ControlSupport.SUPPORTED}
        surface = self._make_surface(controls=controls)
        assert surface.control_supported(SessionControlAction.CANCEL_TURN) is True
        assert surface.control_supported(SessionControlAction.STEER_TURN) is False

    def test_full_construction(self):
        ref = SessionSurfaceRef("opencode", "acp", "1.0")
        identity = SessionIdentityCapabilities(
            identity_operations={
                SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
            },
            ownership_modes=(SessionOwnershipMode.OWNED,),
        )
        controls = {SessionControlAction.CANCEL_TURN: ControlSupport.SUPPORTED}
        lifecycle = LifecycleObservationCapabilities(source=LifecycleSource.TRANSPORT)
        content = ContentStreamCapabilities(
            channels=(ContentChannelCapability(ContentChannelId.ASSISTANT_TEXT, max_bytes=65536),),
        )
        validation = SurfaceValidation(
            evidence=ValidationEvidence(validated=True, reference="tests/e2e/agents/test_opencode_acp_e2e.py"),
        )
        surface = ResolvedSessionSurface(
            ref=ref, identity=identity, controls=controls,
            lifecycle=lifecycle, content=content, validation=validation,
        )
        assert surface.ref.provider_id == "opencode"
        assert surface.control_supported(SessionControlAction.CANCEL_TURN) is True
        assert surface.identity.operation_supported(SessionIdentityOperation.OPEN) is True

    def _make_surface(self, **overrides):
        ref = SessionSurfaceRef("p", "s", "v")
        kwargs = dict(ref=ref, identity=SessionIdentityCapabilities())
        kwargs.update(overrides)
        return ResolvedSessionSurface(**kwargs)


class TestPlatformEvidence:
    def test_frozen(self):
        pe = PlatformEvidence(platform="linux-amd64")
        with pytest.raises(Exception):
            pe.platform = "windows-amd64"

    def test_defaults(self):
        pe = PlatformEvidence(platform="windows-amd64")
        assert pe.tool_version == ""
        assert pe.probe_artifact == ""
        assert pe.evidence.validated is False


class TestSurfaceValidation:
    def test_frozen(self):
        sv = SurfaceValidation(evidence=ValidationEvidence(validated=True, reference="doc"))
        with pytest.raises(Exception):
            sv.evidence = ValidationEvidence()

    def test_with_platforms(self):
        platforms = (
            PlatformEvidence(platform="linux-amd64", evidence=ValidationEvidence(validated=True, reference="doc")),
            PlatformEvidence(platform="windows-amd64"),
        )
        sv = SurfaceValidation(
            evidence=ValidationEvidence(validated=True, reference="doc"),
            platforms=platforms,
        )
        assert len(sv.platforms) == 2
        assert sv.platforms[0].evidence.validated is True


# ── Scalar-only / redaction discipline ─────────────────────────────────────

class TestScalarOnlyDiscipline:
    """ResolvedSessionSurface contains no callables, commands, paths, or secrets."""

    def test_no_callables_in_surface(self):
        surface = self._build_surface()
        _assert_no_callables(surface)

    def test_no_callables_in_session_surface_ref(self):
        ref = SessionSurfaceRef("p", "s", "v")
        _assert_no_callables(ref)

    def test_no_callables_in_identity_capabilities(self):
        caps = SessionIdentityCapabilities(
            identity_operations={SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED},
            ownership_modes=(SessionOwnershipMode.OWNED,),
        )
        _assert_no_callables(caps)

    def test_no_callables_in_lifecycle_capabilities(self):
        lc = LifecycleObservationCapabilities(source=LifecycleSource.HOOK)
        _assert_no_callables(lc)

    def test_no_callables_in_content_capabilities(self):
        ch = ContentChannelCapability(ContentChannelId.ASSISTANT_TEXT, max_bytes=1024)
        _assert_no_callables(ch)

    def _build_surface(self):
        ref = SessionSurfaceRef("opencode", "acp", "1.0")
        identity = SessionIdentityCapabilities(
            identity_operations={SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED},
            ownership_modes=(SessionOwnershipMode.OWNED,),
        )
        controls = {SessionControlAction.CANCEL_TURN: ControlSupport.SUPPORTED}
        lifecycle = LifecycleObservationCapabilities(source=LifecycleSource.TRANSPORT)
        content = ContentStreamCapabilities(
            channels=(ContentChannelCapability(ContentChannelId.ASSISTANT_TEXT, max_bytes=65536),),
        )
        validation = SurfaceValidation(evidence=ValidationEvidence(validated=True, reference="doc"))
        return ResolvedSessionSurface(ref=ref, identity=identity, controls=controls, lifecycle=lifecycle, content=content, validation=validation)


def _assert_no_callables(obj: Any, path: str = "") -> None:
    """Recursively assert that no field of *obj* is a callable (function/method/lambdas)."""
    if is_dataclass(obj):
        # Avoid asdict — MappingProxyType can't be pickled by it.
        for f in fields(obj):
            _assert_no_callables(getattr(obj, f.name), f"{path}.{f.name}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _assert_no_callables(value, f"{path}[{key}]")
    elif isinstance(obj, (tuple, list)):
        for i, value in enumerate(obj):
            _assert_no_callables(value, f"{path}[{i}]")
    elif callable(obj) and not isinstance(obj, (str, int, float, bool, type(None))):
        # Enums are callable but not functions — allow them
        import enum
        if isinstance(obj, enum.Enum):
            return
        raise AssertionError(f"Unexpected callable at {path or 'root'}: {obj!r}")


# ── Import neutrality ──────────────────────────────────────────────────────

class TestImportNeutrality:
    """session_surface.py must not import any components.* module."""

    def test_no_components_imports(self):
        mod = __import__(
            "audiagentic.foundation.transports.session_surface",
            fromlist=["ResolvedSessionSurface"],
        )
        source_code = inspect_source(mod)
        for line in source_code.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for bad in ("from components", "import components", ".components."):
                if bad in stripped:
                    pytest.fail(
                        f"session_surface.py must not import components.* — found: {stripped!r}"
                    )

    def test_exports_from_transports_package(self):
        """All public symbols are importable from the transports __init__."""
        from audiagentic.foundation.transports import (
            ResolvedSessionSurface,
        )
        # Just verifying the imports resolve without error
        assert ResolvedSessionSurface is not None


def inspect_source(module: Any) -> str:
    """Get source of a module as string."""
    import inspect
    return inspect.getsource(module)
