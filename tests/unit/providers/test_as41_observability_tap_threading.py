"""AS41 — enable_observability_tap threading from prepare_provider_session_transport

down to a concrete PreSpawnHook, against the REAL pi.yaml/opencode.yaml
descriptors and REAL build_acp_launch functions (not fakes) — this is
specifically proving the inspect.signature(builder) guard against the real
provider adapters, which fakes can't exercise honestly.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.services.config.provider_config import (
    set_provider_enabled,
)
from audiagentic.components.providers.services.execution.public_execution import (
    prepare_provider_session_transport,
)


class TestObservabilityTapThreading:
    def test_pi_gets_hook_when_tap_requested_on_a_platform_with_evidence(self, tmp_path: Path):
        """pi-community-acp is only inventory-proven on linux-amd64 this
        session — force that platform_hint so this test doesn't depend on
        which host it runs on."""
        set_provider_enabled(tmp_path, "pi", enabled=True)

        prepared = prepare_provider_session_transport(
            tmp_path,
            provider_id="pi",
            surface_hint=SurfaceHint(surface_id="pi-community-acp", platform_hint="linux-amd64"),
            model_id="audiagentic/audiagentic-rig",
            request_runtime_root=tmp_path / "runtime",
            enable_observability_tap=True,
        )

        assert prepared.transport is not None
        from audiagentic.components.providers.adapters.pi.rpc_tap_evidence import (
            PiRpcTapPreSpawnHook,
        )

        assert isinstance(prepared.transport._inner._pre_spawn_hook, PiRpcTapPreSpawnHook)

    def test_pi_no_hook_when_tap_not_requested(self, tmp_path: Path):
        set_provider_enabled(tmp_path, "pi", enabled=True)

        prepared = prepare_provider_session_transport(
            tmp_path,
            provider_id="pi",
            surface_hint=SurfaceHint(surface_id="pi-community-acp", platform_hint="linux-amd64"),
            model_id="audiagentic/audiagentic-rig",
            request_runtime_root=tmp_path / "runtime",
            enable_observability_tap=False,
        )

        assert prepared.transport is not None
        assert prepared.transport._inner._pre_spawn_hook is None

    def test_pi_no_hook_without_request_runtime_root(self, tmp_path: Path):
        """enable_rpc_tap requires request_runtime_root (build_acp_launch's
        own precondition) — asking for tap without one must not attach a
        hook doomed to fail, and must not crash the factory either."""
        set_provider_enabled(tmp_path, "pi", enabled=True)

        prepared = prepare_provider_session_transport(
            tmp_path,
            provider_id="pi",
            surface_hint=SurfaceHint(surface_id="pi-community-acp", platform_hint="linux-amd64"),
            model_id="audiagentic/audiagentic-rig",
            enable_observability_tap=True,
        )

        assert prepared.transport is not None
        assert prepared.transport._inner._pre_spawn_hook is None

    def test_opencode_never_gets_a_hook_even_when_tap_requested(self, tmp_path: Path):
        """OpenCode's build_acp_launch has no enable_rpc_tap parameter — the
        signature guard must silently skip attaching anything, never error."""
        set_provider_enabled(tmp_path, "opencode", enabled=True)

        prepared = prepare_provider_session_transport(
            tmp_path,
            provider_id="opencode",
            surface_hint=SurfaceHint(surface_id="opencode-acp", platform_hint="linux-amd64"),
            model_id="some-model",
            request_runtime_root=tmp_path / "runtime",
            enable_observability_tap=True,
        )

        assert prepared.transport is not None
        assert prepared.transport._inner._pre_spawn_hook is None
