"""AS29 ownership proof for the public session-surface preparation API.

This test deliberately uses the checked-in Pi descriptor and the real provider
adapter.  It validates resolution and transport construction only; opening the
ACP child belongs to the provider integration/e2e tests.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.services.config.provider_config import (
    set_provider_enabled,
)
from audiagentic.foundation.transports.acp import AcpAgentSessionTransport
from audiagentic.foundation.transports.session_surface import (
    ContentChannelId,
    ResolvedSessionSurface,
    SessionControlAction,
)

pytestmark = pytest.mark.skipif(
    shutil.which("pi") is None or shutil.which("npx") is None,
    reason="the real Pi ACP adapter requires pi and npx on PATH",
)


def test_pi_acp_surface_resolves_through_public_api(tmp_path: Path) -> None:
    """Resolve Pi ACP from the real descriptor and prepare its neutral transport."""
    set_provider_enabled(tmp_path, "pi", enabled=True)

    prepared = providers_api.prepare_provider_session_transport(
        tmp_path,
        ag_session_id="ag-test-session",
        binding_sink=lambda update: None,
        provider_id="pi",
        surface_hint=SurfaceHint(
            surface_id="pi-community-acp",
            platform_hint="linux-amd64",
        ),
        model_id="audiagentic/audiagentic-rig",
        request_runtime_root=tmp_path / "runtime",
    )

    assert isinstance(prepared.surface, ResolvedSessionSurface)
    assert prepared.surface.ref.provider_id == "pi"
    assert prepared.surface.ref.surface_id == "pi-community-acp"
    assert prepared.surface.validation.evidence.validated is True
    assert prepared.surface.validation.evidence.reference
    assert prepared.surface.content.has_channel(ContentChannelId.ASSISTANT_TEXT)
    assistant_text = next(
        channel
        for channel in prepared.surface.content.channels
        if channel.channel == ContentChannelId.ASSISTANT_TEXT
    )
    assert assistant_text.max_bytes > 0
    assert assistant_text.max_events > 0
    assert prepared.surface.control_supported(SessionControlAction.CANCEL_TURN)
    assert isinstance(prepared.transport, AcpAgentSessionTransport)
    assert prepared.transport is not None
    assert prepared.surface is not None
