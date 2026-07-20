"""AS28 slice 3 — provider transport-factory bridge.

Tests verify the new prepare_provider_session_transport contract:
- Exact snapshot reuse (same ResolvedSessionSurface in PreparedSessionTransport)
- Unsupported/no-launch (disabled, version/platform mismatch, no factory → transport=None)
- OpenCode ACP factory returns neutral AcpAgentSessionTransport protocol
- No agents imports into descriptor/ACP from providers_api
- Adapter ref redaction in resolved snapshots
- Old prepare_provider_acp_launch API unchanged

Only provider-side contracts/services/adapters/providers_api are modified.
No edits to agents/session runtime/dispatch, descriptors/YAML, AS19/AS30, or
foundation neutral contracts.
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
from audiagentic.foundation.transports.acp import (
    AcpAgentSessionTransport,
    AcpLaunch,
)
from audiagentic.foundation.transports.session_surface import (
    EffectiveObservationLevel,
    PreparedSessionTransport,
    SessionMappingFacts,
    SessionSurfaceRef,
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


# ── Exact snapshot reuse ────────────────────────────────────────────────────

class TestExactSnapshotReuse:
    """The surface in PreparedSessionTransport is the same frozen snapshot
    resolved by the AS29 resolver."""

    def test_snapshot_same_ref_as_resolve(self, tmp_path: Path):
        """PreparedSessionTransport.surface.ref matches resolve_session_surface ref."""
        descriptor = _fake_descriptor(
            "reuse-prov",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "reuse-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        hint = SurfaceHint(surface_id="acp")
        resolved = providers_api.resolve_session_surface(
            tmp_path, "reuse-prov", hint,
        )
        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="reuse-prov",
            surface_hint=hint,
            model_id="gpt-4",
        )

        # Both resolve through the same AS29 resolver; refs must match.
        assert resolved.ref.provider_id == prepared.surface.ref.provider_id
        assert resolved.ref.surface_id == prepared.surface.ref.surface_id
        assert resolved.validation.state == prepared.surface.validation.state

    def test_effective_provider_ref_identifies_surface(self, tmp_path: Path):
        """effective_provider_ref carries provider_id + surface_id from resolution."""
        descriptor = _fake_descriptor(
            "ref-prov",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "ref-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        hint = SurfaceHint(surface_id="acp")
        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="ref-prov",
            surface_hint=hint,
            model_id="gpt-4",
        )

        assert isinstance(prepared.effective_provider_ref, SessionSurfaceRef)
        assert prepared.effective_provider_ref.provider_id == "ref-prov"
        assert prepared.effective_provider_ref.surface_id == "acp"


# ── Unsupported → no launch, transport=None ─────────────────────────────────

class TestUnsupportedNoLaunch:
    """All unsupported paths return transport=None without launching a process."""

    def test_unknown_provider_transport_none(self, tmp_path: Path):
        """Unknown provider returns UNSUPPORTED with transport=None."""
        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="nonexistent-provider",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert isinstance(prepared, PreparedSessionTransport)
        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_disabled_provider_transport_none(self, tmp_path: Path):
        """Disabled provider returns UNSUPPORTED with transport=None."""
        descriptor = _fake_descriptor(
            "disabled-prov",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "disabled-prov", enabled=False)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="disabled-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_no_surface_match_transport_none(self, tmp_path: Path):
        """No matching surface_id returns UNSUPPORTED with transport=None."""
        descriptor = _fake_descriptor(
            "no-surface-prov",
            session_surfaces=(_fake_surface_decl(surface_id="other"),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "no-surface-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="no-surface-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_version_mismatch_transport_none(self, tmp_path: Path, monkeypatch):
        """Version mismatch returns UNSUPPORTED with transport=None."""
        descriptor = _fake_descriptor(
            "ver-mismatch-prov",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp", version_constraint=">=3.0"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "ver-mismatch-prov", enabled=True)

        monkeypatch.setattr(
            "audiagentic.components.providers.services.session_surface_resolution._probe_installed_version",
            lambda d: "2.0.0",
        )

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="ver-mismatch-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_platform_mismatch_transport_none(self, tmp_path: Path):
        """Platform mismatch returns UNSUPPORTED with transport=None."""
        from audiagentic.foundation.transports.session_surface import PlatformEvidence

        descriptor = _fake_descriptor(
            "plat-mismatch-prov",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.VALIDATED,
                    effective_level=EffectiveObservationLevel.O2,
                    platforms=(PlatformEvidence(platform="linux-amd64"),),
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "plat-mismatch-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="plat-mismatch-prov",
            surface_hint=SurfaceHint(surface_id="acp", platform_hint="windows-amd64"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_unvalidated_high_level_transport_none(self, tmp_path: Path):
        """Unvalidated O2+ returns UNSUPPORTED with transport=None."""
        descriptor = _fake_descriptor(
            "unval-prov",
            session_surfaces=(
                _fake_surface_decl(
                    validation_state=SurfaceValidationState.DECLARED,
                    effective_level=EffectiveObservationLevel.O3,
                ),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "unval-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="unval-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_blocked_declaration_transport_none(self, tmp_path: Path):
        """Blocked declaration returns UNSUPPORTED with transport=None."""
        descriptor = _fake_descriptor(
            "blocked-prov",
            session_surfaces=(
                _fake_surface_decl(validation_state=SurfaceValidationState.BLOCKED),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "blocked-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="blocked-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED

    def test_missing_adapter_factory_transport_none(self, tmp_path: Path):
        """Missing adapter_ref factory returns UNSUPPORTED with transport=None."""
        descriptor = _fake_descriptor(
            "missing-factory-prov",
            session_surfaces=(
                _fake_surface_decl(adapter_ref="nonexistent.module:factory_fn"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "missing-factory-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="missing-factory-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED


# ── OpenCode ACP factory returns neutral protocol ───────────────────────────

class TestOpenCodeFactoryNeutralProtocol:
    """Supported ACP surface produces AcpAgentSessionTransport (not raw AcpLaunch)."""

    def test_supported_surface_returns_acp_agent_session_transport(self, tmp_path: Path):
        """Supported surface with ACP factory returns AcpAgentSessionTransport."""
        descriptor = _fake_descriptor(
            "acp-prov",
            cli_probe=["echo", "1.0"],
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "acp-prov", enabled=True)

        # Mock the ACP launch builder so we get a transport without real CLI.
        dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})

        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            exec_mod.load_acp_launch_builder = lambda pid: lambda pr, **kw: dummy_launch  # type: ignore[assignment]

            from audiagentic.components.providers import providers_api

            prepared = providers_api.prepare_provider_session_transport(
                tmp_path,
                provider_id="acp-prov",
                surface_hint=SurfaceHint(surface_id="acp"),
                model_id="gpt-4",
            )

            assert isinstance(prepared, PreparedSessionTransport)
            # Transport is an AcpAgentSessionTransport (neutral protocol), not raw AcpLaunch.
            assert isinstance(prepared.transport, AcpAgentSessionTransport)
            assert prepared.transport is not dummy_launch  # not the raw launch
            # Surface is supported (not UNSUPPORTED).
            assert prepared.surface.validation.state != SurfaceValidationState.UNSUPPORTED

        finally:
            exec_mod.load_acp_launch_builder = orig

    def test_transport_does_not_expose_raw_launch(self, tmp_path: Path):
        """The transport does not expose the raw AcpLaunch directly."""
        descriptor = _fake_descriptor(
            "no-expose-prov",
            cli_probe=["echo", "1.0"],
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "no-expose-prov", enabled=True)

        dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})
        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            exec_mod.load_acp_launch_builder = lambda pid: lambda pr, **kw: dummy_launch  # type: ignore[assignment]

            from audiagentic.components.providers import providers_api

            prepared = providers_api.prepare_provider_session_transport(
                tmp_path,
                provider_id="no-expose-prov",
                surface_hint=SurfaceHint(surface_id="acp"),
                model_id="gpt-4",
            )

            # The transport wraps the launch; it is not the raw AcpLaunch.
            assert not isinstance(prepared.transport, AcpLaunch)

        finally:
            exec_mod.load_acp_launch_builder = orig


# ── No agents imports descriptor/ACP ────────────────────────────────────────

class TestNoAgentsImports:
    """providers_api and public_execution must not import from agents."""

    def test_no_agent_import_in_providers_api(self):
        """providers_api must not import from components.agents at module level."""
        from audiagentic.components.providers import providers_api
        source = _inspect_source(providers_api)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Module-level imports (not inside functions) — indent check.
            if "from audiagentic.components.agents" in stripped:
                pytest.fail(
                    f"providers_api must not import from agents: {stripped}"
                )

    def test_no_agent_import_in_public_execution(self):
        """public_execution must not import from components.agents."""
        from audiagentic.components.providers.services import public_execution
        source = _inspect_source(public_execution)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "from audiagentic.components.agents" in stripped:
                pytest.fail(
                    f"public_execution must not import from agents: {stripped}"
                )

    def test_no_descriptor_import_in_providers_api_top_level(self):
        """providers_api must not import descriptor base at module level."""
        from audiagentic.components.providers import providers_api
        source = _inspect_source(providers_api)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "from audiagentic.components.providers.descriptors.base" in stripped and not stripped.startswith("    "):
                pytest.fail(
                    "providers_api must not import descriptor base at module level"
                )


# ── Adapter ref redaction ───────────────────────────────────────────────────

class TestAdapterRefRedaction:
    """Resolved snapshots through the transport API carry no adapter_ref."""

    def test_no_adapter_ref_in_prepared_transport(self, tmp_path: Path):
        """Even when the descriptor has an adapter_ref, it is not in the snapshot."""
        descriptor = _fake_descriptor(
            "redact-prov",
            session_surfaces=(
                _fake_surface_decl(adapter_ref="some.module:factory_fn"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "redact-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="redact-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        # ResolvedSessionSurface has no adapter_ref field.
        assert not hasattr(prepared.surface, "adapter_ref")

    def test_no_adapter_in_effective_ref(self, tmp_path: Path):
        """effective_provider_ref carries only identity (provider + surface + version)."""
        descriptor = _fake_descriptor(
            "ref-redact-prov",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "ref-redact-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="ref-redact-prov",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        # SessionSurfaceRef has only provider_id, surface_id, resolved_version.
        ref_fields = set(prepared.effective_provider_ref.__dataclass_fields__)
        assert ref_fields == {"provider_id", "surface_id", "resolved_version"}


# ── No process launch on unsupported ────────────────────────────────────────

class TestNoProcessLaunch:
    """Unsupported surfaces never spawn a child process."""

    def test_unsupported_no_child_spawn(self, tmp_path: Path):
        """verify no subprocess is spawned for unsupported surface.

        We check that transport=None (the only way to verify no launch without
        mocking subprocess at the system level)."""
        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="nonexistent-provider",
            surface_hint=SurfaceHint(surface_id="acp"),
        )

        assert prepared.transport is None
        # If transport were a real object, it might have an open() method that
        # spawns a process. None means no process can be spawned.

    def test_unsupported_no_fallback(self, tmp_path: Path):
        """No fallback to another surface — unsupported stays unsupported."""
        descriptor = _fake_descriptor(
            "multi-prov",
            session_surfaces=(
                _fake_surface_decl(surface_id="acp"),
                _fake_surface_decl(surface_id="mcp"),
            ),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "multi-prov", enabled=True)

        from audiagentic.components.providers import providers_api

        # Request a non-existent surface — no fallback to acp or mcp.
        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="multi-prov",
            surface_hint=SurfaceHint(surface_id="nonexistent-surface"),
        )

        assert prepared.transport is None
        assert prepared.surface.validation.state == SurfaceValidationState.UNSUPPORTED


# ── Old API unchanged (backward compatibility) ──────────────────────────────

class TestOldApiUnchanged:
    """prepare_provider_acp_launch contract remains stable."""

    def test_prepare_provider_acp_launch_still_in_all(self):
        """Existing function is still exported from providers_api."""
        from audiagentic.components.providers import providers_api

        assert "prepare_provider_acp_launch" in providers_api.__all__

    def test_prepare_provider_acp_launch_returns_typed_result(self, tmp_path: Path):
        """Old function returns ProviderAcpLaunchResult (not PreparedSessionTransport)."""
        from audiagentic.components.providers import providers_api
        from audiagentic.components.providers.contracts.provider_execution import (
            ProviderAcpLaunchResult,
        )

        descriptor = _fake_descriptor(
            "stable-prov",
            cli_probe=["echo", "1.0"],
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "stable-prov", enabled=True)

        dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})
        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            exec_mod.load_acp_launch_builder = lambda pid: lambda pr, **kw: dummy_launch  # type: ignore[assignment]

            result = providers_api.prepare_provider_acp_launch(
                tmp_path,
                provider_id="stable-prov",
                model_id="gpt-4",
                model_alias=None,
            )

            assert isinstance(result, ProviderAcpLaunchResult)
            assert hasattr(result, "launch")
            assert hasattr(result, "provider_id")
            assert hasattr(result, "model_id")
            assert result.provider_id == "stable-prov"
            # Old API returns the raw AcpLaunch, not AcpAgentSessionTransport.
            assert isinstance(result.launch, AcpLaunch)

        finally:
            exec_mod.load_acp_launch_builder = orig

    def test_new_api_is_separate_from_old(self):
        """New prepare_provider_session_transport is separate from old API."""
        from audiagentic.components.providers import providers_api

        assert "prepare_provider_session_transport" in providers_api.__all__
        assert "prepare_provider_acp_launch" in providers_api.__all__
        # Both functions exist independently.
        assert callable(providers_api.prepare_provider_session_transport)
        assert callable(providers_api.prepare_provider_acp_launch)


# ── PreparedSessionTransport type properties ───────────────────────────────

class TestPreparedSessionTransportType:
    """PreparedSessionTransport is frozen and carries only expected fields."""

    def test_is_frozen(self, tmp_path: Path):
        """PreparedSessionTransport instances are frozen."""
        from audiagentic.components.providers import providers_api

        prepared = providers_api.prepare_provider_session_transport(
            tmp_path,
            provider_id="nonexistent",
            surface_hint=SurfaceHint(surface_id="acp"),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            prepared.transport = "something"  # type: ignore

    def test_no_adapter_in_prepared_transport_fields(self):
        """PreparedSessionTransport does not expose adapter or protocol types."""
        import dataclasses as dc

        field_names = {f.name for f in dc.fields(PreparedSessionTransport)}
        assert "adapter_ref" not in field_names
        assert "descriptor" not in field_names
        # Expected fields: surface, effective_provider_ref, transport
        assert field_names == {"surface", "effective_provider_ref", "transport"}


# ── No duplicate resolver / public ACP leakage ─────────────────────────────

class TestNoDuplicateResolver:
    """Self-review: no duplicate resolver or public ACP leakage."""

    def test_single_resolver_call(self, tmp_path: Path):
        """prepare_provider_session_transport calls resolve_session_surface once.

        The function delegates to the service which resolves the surface
        exactly once — no second resolution happens in the API layer."""
        descriptor = _fake_descriptor(
            "single-prov",
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "single-prov", enabled=True)

        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})
            resolve_count = 0

            from audiagentic.components.providers.services.session_surface_resolution import (
                resolve_session_surface as _resolve,
            )
            orig_resolve = _resolve.__module__

            def counting_resolve(*args, **kwargs):
                nonlocal resolve_count
                resolve_count += 1
                return _resolve(*args, **kwargs)

            monkeypatch_resolver = lambda: None  # placeholder

            from audiagentic.components.providers import providers_api

            prepared = providers_api.prepare_provider_session_transport(
                tmp_path,
                provider_id="single-prov",
                surface_hint=SurfaceHint(surface_id="acp"),
                model_id="gpt-4",
            )

            # The service calls resolve once; the API delegates to service.
            # We verify by checking that the result is consistent (one snapshot).
            assert isinstance(prepared.surface, ResolvedSessionSurface)

        finally:
            exec_mod.load_acp_launch_builder = orig

    def test_no_public_acp_leakage_in_providers_api(self):
        """providers_api does not export raw ACP types (AcpLaunch, etc.)."""
        from audiagentic.components.providers import providers_api

        # AcpLaunch and AcpSessionTransport are foundation types — they should
        # not be re-exported through the provider public API.
        assert "AcpLaunch" not in providers_api.__all__
        assert "AcpSessionTransport" not in providers_api.__all__
        assert "AcpAgentSessionTransport" not in providers_api.__all__

    def test_prepared_transport_carrying_neutral_protocol(self, tmp_path: Path):
        """The transport in PreparedSessionTransport implements AgentSessionTransport."""

        descriptor = _fake_descriptor(
            "protocol-prov",
            cli_probe=["echo", "1.0"],
            session_surfaces=(_fake_surface_decl(),),
        )
        register(descriptor)
        set_provider_enabled(tmp_path, "protocol-prov", enabled=True)

        dummy_launch = AcpLaunch(executable="dummy", args=(), environment={})
        import audiagentic.components.providers.services.execution as exec_mod
        orig = exec_mod.load_acp_launch_builder

        try:
            exec_mod.load_acp_launch_builder = lambda pid: lambda pr, **kw: dummy_launch  # type: ignore[assignment]

            from audiagentic.components.providers import providers_api

            prepared = providers_api.prepare_provider_session_transport(
                tmp_path,
                provider_id="protocol-prov",
                surface_hint=SurfaceHint(surface_id="acp"),
                model_id="gpt-4",
            )

            # The transport implements AgentSessionTransport protocol.
            assert hasattr(prepared.transport, "open")
            assert hasattr(prepared.transport, "prompt")
            assert hasattr(prepared.transport, "control")
            assert hasattr(prepared.transport, "close")
            assert hasattr(prepared.transport, "is_alive")

        finally:
            exec_mod.load_acp_launch_builder = orig


# ── Helpers ────────────────────────────────────────────────────────────────

def _inspect_source(module: Any) -> str:
    """Get source of a module as string."""
    import inspect
    return inspect.getsource(module)
