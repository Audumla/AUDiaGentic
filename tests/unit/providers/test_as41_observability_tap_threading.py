"""AS41 — enable_observability_tap threading from prepare_provider_session_transport

down to a concrete PreSpawnHook. Two tiers, deliberately:

``TestObservabilityTapThreading`` runs against the REAL pi.yaml/opencode.yaml
descriptors and REAL build_acp_launch functions, proving the
``inspect.signature(builder)`` guard against the actual provider adapters.
Pi's real builder resolves the ``pi`` CLI plus ``npx``/``pi-acp``, and the
opencode case needs the ``opencode`` CLI, so these are gated on all three. An
``npx``-only gate is not enough: the Docker test image ships Node but no
provider CLIs, and the tests failed there with ``RES-PIACP-002`` (Pi CLI not
found) and ``EXT-PROVCLI-001`` (opencode not found). They are the pi-canary
proof and run wherever the real CLIs exist.

``TestSignatureGuardWithFakeBuilders`` proves the same branch logic with fake
builders and no external dependency, so CI always covers the mechanism. It is
provider-neutral on purpose: as harnesses beyond the pi canary arrive, this is
the coverage that keeps working without a matching real-binary dependency.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.services.config.provider_config import (
    set_provider_enabled,
)
from audiagentic.components.providers.services.execution.public_execution import (
    prepare_provider_session_transport,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.acp import AcpLaunch


@pytest.mark.requires_npm
@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not on PATH")
@pytest.mark.skipif(shutil.which("pi") is None, reason="pi CLI not on PATH")
@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode CLI not on PATH")
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


class _FakeHook:
    """Stands in for a provider's concrete PreSpawnHook."""


def _tap_aware_builder(project_root, *, model_id, request_runtime_root=None,
                       enable_rpc_tap=False, mcp_surface=None):
    """A builder that declares enable_rpc_tap, as pi's real one does."""
    return AcpLaunch(executable="fake-agent", args=("--acp",))


def _tap_blind_builder(project_root, *, model_id, request_runtime_root=None,
                       mcp_surface=None):
    """A builder with no enable_rpc_tap parameter, as most adapters have."""
    return AcpLaunch(executable="fake-agent", args=("--acp",))


class TestSignatureGuardWithFakeBuilders:
    """The same branch logic, with no dependency on a real provider binary.

    These use pi's real descriptor so the surface resolves as supported, but
    substitute the launch builder — the assertion is about wiring, so nothing
    here needs Node.
    """

    @staticmethod
    def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder, **kwargs):
        from audiagentic.components.providers.services.execution import (
            execution,
            public_execution,
        )

        set_provider_enabled(tmp_path, "pi", enabled=True)
        monkeypatch.setattr(execution, "load_acp_launch_builder", lambda _pid: builder)
        monkeypatch.setattr(
            public_execution, "_observability_hook_factories", lambda: {"pi": _FakeHook}
        )
        return prepare_provider_session_transport(
            tmp_path,
            provider_id="pi",
            surface_hint=SurfaceHint(surface_id="pi-community-acp", platform_hint="linux-amd64"),
            model_id="audiagentic/audiagentic-rig",
            request_runtime_root=tmp_path / "runtime",
            **kwargs,
        )

    def test_hook_attached_when_builder_declares_the_kwarg(self, tmp_path, monkeypatch):
        prepared = self._prepare(
            tmp_path, monkeypatch, _tap_aware_builder, enable_observability_tap=True
        )

        assert prepared.transport is not None
        assert isinstance(prepared.transport._inner._pre_spawn_hook, _FakeHook)

    def test_no_hook_when_builder_does_not_declare_the_kwarg(self, tmp_path, monkeypatch):
        """The guard must skip a builder that cannot accept the kwarg, rather
        than passing it and raising TypeError."""
        prepared = self._prepare(
            tmp_path, monkeypatch, _tap_blind_builder, enable_observability_tap=True
        )

        assert prepared.transport is not None
        assert prepared.transport._inner._pre_spawn_hook is None

    def test_classified_builder_failure_is_reported_not_swallowed(self, tmp_path, monkeypatch):
        """A registered AudiaGenticError from the builder must reach the caller
        as a classification, not vanish into a bare transport=None.

        Uses EXT-PROVCLI-001 rather than pi's own RES-PIACP-001 because the
        latter is not registered in the error catalogue and so cannot be
        constructed at all — see the make_error registration gap recorded in
        AS71's Notes.
        """

        def failing_builder(project_root, **kwargs):
            raise AudiaGenticError(
                code="EXT-PROVCLI-001",
                kind="providers",
                message="provider executable not found on PATH",
            )

        prepared = self._prepare(tmp_path, monkeypatch, failing_builder)

        assert prepared.transport is None
        assert prepared.unavailable_code == "EXT-PROVCLI-001"
        assert "not found on PATH" in prepared.unavailable_message

    def test_unclassified_builder_failure_is_reported(self, tmp_path, monkeypatch):
        def exploding_builder(project_root, **kwargs):
            raise RuntimeError("boom")

        prepared = self._prepare(tmp_path, monkeypatch, exploding_builder)

        assert prepared.transport is None
        assert prepared.unavailable_code == "EXT-PROVEXEC-901"
        assert "boom" in prepared.unavailable_message

    def test_builder_contract_violation_is_reported(self, tmp_path, monkeypatch):
        prepared = self._prepare(tmp_path, monkeypatch, lambda project_root, **kw: "not-a-launch")

        assert prepared.transport is None
        assert prepared.unavailable_code == "EXT-PROVEXEC-902"
        assert "str" in prepared.unavailable_message
