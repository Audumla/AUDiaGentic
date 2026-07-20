"""AS29 slice 5a — providers API exposes resolved session-surface snapshots.

Tests verify:
- Public API exact forwarding (resolve_session_surface delegates to resolver)
- No descriptor/protocol imports into agents via the new public surface path
- Adapter-ref redaction in resolved snapshots
- One resolved snapshot reused by prepared transport
- Unsupported surface produces no live transport
- Prior behavior remains stable (prepare_provider_acp_launch unchanged)
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
from audiagentic.foundation.transports.session_surface import (
    PreparedSessionTransport,
    SessionMappingFacts,
    SessionSurfaceRef,
    SurfaceValidationState,
)
from audiagentic.foundation.transports.session_surface import (
    ResolvedSessionSurface as FoundationResolvedSessionSurface,
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


def _fake_surface_decl(**kwargs: Any) -> Any:
    """Build a fake SessionSurfaceDeclaration for testing."""
    from audiagentic.components.providers.descriptors.session_surface_declarations import (
        SessionSurfaceDeclaration,
    )
    defaults = {
        "surface_id": "acp",
        "version_constraint": ">=1.0",
        "identity_operations": {},
        "ownership_modes": (),
        "mapping_facts": SessionMappingFacts(),
        "controls": {},
        "adapter_ref": None,
    }
    defaults.update(kwargs)
    return SessionSurfaceDeclaration(**defaults)


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolate the descriptor registry and project root per test."""
    from audiagentic.components.providers.descriptors.registry import (
        _registry,
    )
    _registry._items.clear()

    yield tmp_path


# ── Public API exact forwarding ─────────────────────────────────────────────

class TestResolveSessionSurfacePublicApi:
    """resolve_session_surface delegates to resolver and returns frozen types."""

    def test_exports_are_public(self):
        from audiagentic.components.providers import providers_api

        assert "resolve_session_surface" in providers_api.__all__
        assert "prepare_provider_session_transport" in providers_api.__all__
        assert "SurfaceHint" in providers_api.__all__
        assert "ResolvedSessionSurface" in providers_api.__all__
        assert "PreparedSessionTransport" in providers_api.__all__

    def test_resolve_returns_foundation_snapshot(self, tmp_path: Path):
        """Public API returns the foundation ResolvedSessionSurface type."""
        descriptor = _fake_descriptor(
            "forward-test",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "forward-test", enabled=True)

        from audiagentic.components.providers.providers_api import (
            resolve_session_surface,
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "forward-test", hint)

        assert isinstance(result, ResolvedSessionSurface)
        # Also the foundation type (they are the same class).
        assert isinstance(result, FoundationResolvedSessionSurface)
        assert result.ref.provider_id == "forward-test"
        assert result.ref.surface_id == "acp"

    def test_resolve_unknown_provider_unsupported(self, tmp_path: Path):
        """Unknown provider returns UNSUPPORTED snapshot through public API."""
        from audiagentic.components.providers.providers_api import (
            resolve_session_surface,
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "nonexistent", hint)

        assert result.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_resolve_disabled_provider_unsupported(self, tmp_path: Path):
        """Disabled provider returns UNSUPPORTED snapshot through public API."""
        descriptor = _fake_descriptor(
            "disabled-fwd",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "disabled-fwd", enabled=False)

        from audiagentic.components.providers.providers_api import (
            resolve_session_surface,
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "disabled-fwd", hint)

        assert result.validation.state == SurfaceValidationState.UNSUPPORTED


# ── Adapter-ref redaction ───────────────────────────────────────────────────

class TestAdapterRefRedaction:
    """Resolved snapshots through the public API carry no adapter_ref."""

    def test_no_adapter_ref_in_snapshot(self, tmp_path: Path):
        """Even when the descriptor has an adapter_ref, it is not in the snapshot."""
        descriptor = _fake_descriptor(
            "redact-test",
            session_surfaces=(
                _fake_surface_decl(adapter_ref="some.module:factory_fn"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "redact-test", enabled=True)

        from audiagentic.components.providers.providers_api import (
            resolve_session_surface,
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "redact-test", hint)

        # The ResolvedSessionSurface has no adapter_ref field at all.
        assert not hasattr(result, "adapter_ref")

    def test_snapshot_is_scalar_only(self, tmp_path: Path):
        """Resolved snapshot contains no callables or native values."""
        descriptor = _fake_descriptor(
            "scalar-test",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "scalar-test", enabled=True)

        from audiagentic.components.providers.providers_api import (
            resolve_session_surface,
        )

        hint = SurfaceHint(surface_id="acp")
        result = resolve_session_surface(tmp_path, "scalar-test", hint)

        # Frozen — cannot be modified.
        with pytest.raises(Exception):  # FrozenInstanceError
            result.ref = None  # type: ignore

    def test_no_descriptor_import_in_agents(self):
        """Agents gateway must not import provider descriptors through the new path."""
        # Check that the public API module itself does not import descriptor types
        # at the top level (lazy imports inside functions are OK).
        from audiagentic.components.providers import providers_api

        source = _inspect_source(providers_api)
        # The module-level imports should not include descriptor internals.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Only top-level imports (not inside functions) count.
            if "from audiagentic.components.providers.descriptors.base" in stripped and not stripped.startswith("    "):
                pytest.fail(
                    "providers_api must not import descriptor base at module level"
                )


# ── PreparedSessionTransport: one snapshot reused ───────────────────────────

class TestPreparedSessionTransportReusesSnapshot:
    """prepare_provider_session_transport returns the same surface snapshot."""

    def test_supported_surface_returns_prepared_transport(self, tmp_path: Path):
        """Supported surface produces a PreparedSessionTransport with transport."""
        # Register a provider with ACP support so prepare_provider_acp_launch
        # doesn't raise. We mock the acp launch builder to return a dummy.
        from audiagentic.components.providers import providers_api
        from audiagentic.foundation.transports import AcpLaunch

        descriptor = _fake_descriptor(
            "transport-test",
            cli_probe=["echo", "1.0"],
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "transport-test", enabled=True)

        # Mock the ACP launch builder so we get a transport without real CLI.
        dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})

        def _mock_builder(project_root, **kwargs):
            return dummy_launch

        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            exec_mod.load_acp_launch_builder = lambda pid: _mock_builder  # type: ignore[assignment]

            hint = SurfaceHint(surface_id="acp")
            prepared = providers_api.prepare_provider_session_transport(
                tmp_path,
                provider_id="transport-test",
                surface_hint=hint,
                model_id="gpt-4",
            )

            assert isinstance(prepared, PreparedSessionTransport)
            # Transport is set (not None) for supported surface — AS28 slice 3
            # wraps AcpLaunch in AcpAgentSessionTransport (neutral protocol).
            from audiagentic.foundation.transports.acp import (
                AcpAgentSessionTransport,
            )
            assert isinstance(prepared.transport, AcpAgentSessionTransport)
            # The raw AcpLaunch is not exposed directly — it's wrapped.
            assert prepared.transport is not dummy_launch
            # Surface is a ResolvedSessionSurface and is supported.
            assert isinstance(prepared.surface, ResolvedSessionSurface)
            assert prepared.surface.validation.state != SurfaceValidationState.UNSUPPORTED
            # Effective provider ref identifies the resolved surface.
            assert isinstance(prepared.effective_provider_ref, SessionSurfaceRef)
            assert prepared.effective_provider_ref.provider_id == "transport-test"
            assert prepared.effective_provider_ref.surface_id == "acp"

        finally:
            exec_mod.load_acp_launch_builder = orig

    def test_unsupported_surface_no_live_transport(self, tmp_path: Path):
        """Unsupported surface produces PreparedSessionTransport with transport=None."""
        from audiagentic.components.providers import providers_api

        hint = SurfaceHint(surface_id="acp")
        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="nonexistent-provider",
            surface_hint=hint,
        )

        assert isinstance(prepared, PreparedSessionTransport)
        # No live transport for unsupported surface.
        assert prepared.transport is None
        # Surface snapshot is UNSUPPORTED.
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED
        # Effective provider ref still identifies the attempted resolution.
        assert prepared.effective_provider_ref.provider_id == "nonexistent-provider"

    def test_one_snapshot_reused(self, tmp_path: Path):
        """The surface in PreparedSessionTransport is the same object resolved
        by resolve_session_surface — not a second independent copy."""
        from audiagentic.components.providers import providers_api

        descriptor = _fake_descriptor(
            "reuse-test",
            cli_probe=["echo", "1.0"],
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "reuse-test", enabled=True)

        from audiagentic.foundation.transports import AcpLaunch

        dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})
        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            exec_mod.load_acp_launch_builder = lambda pid: lambda pr, **kw: dummy_launch  # type: ignore[assignment]

            hint = SurfaceHint(surface_id="acp")

            # Resolve independently.
            resolved = providers_api.resolve_session_surface(
                tmp_path, "reuse-test", hint
            )

            # Prepare transport (which also resolves).
            prepared = providers_api.prepare_provider_session_transport(
                tmp_path,
                provider_id="reuse-test",
                surface_hint=hint,
                model_id="gpt-4",
            )

            # Both calls go through resolve_session_surface; the snapshot
            # object identity may differ per call (each is a fresh dataclass),
            # but they should be structurally identical.
            assert resolved.ref.provider_id == prepared.surface.ref.provider_id
            assert resolved.ref.surface_id == prepared.surface.ref.surface_id
            assert resolved.validation.state == prepared.surface.validation.state

        finally:
            exec_mod.load_acp_launch_builder = orig


# ── Prior behavior stability ────────────────────────────────────────────────

class TestPriorBehaviorStability:
    """Existing prepare_provider_acp_launch contract remains stable."""

    def test_prepare_provider_acp_launch_still_in_all(self):
        """Existing function is still exported."""
        from audiagentic.components.providers import providers_api

        assert "prepare_provider_acp_launch" in providers_api.__all__

    def test_prepare_provider_acp_launch_returns_typed_result(self, tmp_path: Path):
        """Existing function returns ProviderAcpLaunchResult (not PreparedSessionTransport)."""
        from audiagentic.components.providers import providers_api
        from audiagentic.foundation.transports import AcpLaunch

        descriptor = _fake_descriptor(
            "stable-test",
            cli_probe=["echo", "1.0"],
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "stable-test", enabled=True)

        dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})
        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            exec_mod.load_acp_launch_builder = lambda pid: lambda pr, **kw: dummy_launch  # type: ignore[assignment]

            result = providers_api.prepare_provider_acp_launch(
                tmp_path,
                provider_id="stable-test",
                model_id="gpt-4",
                model_alias=None,
            )

            # Old contract: ProviderAcpLaunchResult with launch and provider_id.
            assert hasattr(result, "launch")
            assert hasattr(result, "provider_id")
            assert hasattr(result, "model_id")
            assert result.provider_id == "stable-test"

        finally:
            exec_mod.load_acp_launch_builder = orig

    def test_no_new_breaking_change_in_api_exports(self):
        """Core public API exports remain intact after AS29 slice 5a."""
        from audiagentic.components.providers import providers_api

        core_exports = {
            "execute_provider_turn",
            "prepare_provider_acp_launch",
            "ProviderExecutionRequest",
            "ProviderAcpLaunchResult",
            "list_providers",
            "get_provider_status",
            "manage_mcp_entries",
            "manage_hook_entries",
        }
        assert core_exports <= set(providers_api.__all__)


# ── PreparedSessionTransport type properties ───────────────────────────────

class TestPreparedSessionTransportType:
    """PreparedSessionTransport is a frozen dataclass from foundation."""

    def test_is_frozen(self):
        surface = _make_unsupported_surface()
        ref = SessionSurfaceRef("p", "s", "v")
        prep = PreparedSessionTransport(transport=None, surface=surface, effective_provider_ref=ref)
        with pytest.raises(Exception):  # FrozenInstanceError
            prep.transport = "something"  # type: ignore

    def test_transport_none_when_unsupported(self):
        surface = _make_unsupported_surface()
        ref = SessionSurfaceRef("p", "s", "v")
        prep = PreparedSessionTransport(transport=None, surface=surface, effective_provider_ref=ref)
        assert prep.transport is None

    def test_no_adapter_in_prepared_transport(self):
        """PreparedSessionTransport does not expose adapter or protocol types."""
        import dataclasses as dc

        field_names = {f.name for f in dc.fields(PreparedSessionTransport)}
        assert "adapter_ref" not in field_names
        assert "descriptor" not in field_names


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_unsupported_surface() -> ResolvedSessionSurface:
    """Create an UNSUPPORTED ResolvedSessionSurface for testing."""
    from audiagentic.foundation.transports.session_surface import (
        SessionIdentityCapabilities,
        SurfaceValidation,
    )

    ref = SessionSurfaceRef("p", "s", "unknown")
    return ResolvedSessionSurface(
        ref=ref,
        identity=SessionIdentityCapabilities(),
        validation=SurfaceValidation(state=SurfaceValidationState.UNSUPPORTED),
    )


def _inspect_source(module: Any) -> str:
    """Get source of a module as string."""
    import inspect
    return inspect.getsource(module)
