"""AS31 OutputRelay capability authorization tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.agents_gateway_output import (
    OutputPolicy,
    create_relay,
    read_request_output,
)
from audiagentic.foundation.transports.agent_output import (
    AgentOutputEvent,
    AgentOutputKind,
)
from audiagentic.foundation.transports.session_surface import (
    ContentChannelCapability,
    ContentChannelId,
    ContentStreamCapabilities,
    ResolvedSessionSurface,
    SessionIdentityCapabilities,
    SessionSurfaceRef,
    SurfaceValidation,
    ValidationEvidence,
)


def _surface(*, validated: bool, channels: tuple[ContentChannelCapability, ...]) -> ResolvedSessionSurface:
    return ResolvedSessionSurface(
        ref=SessionSurfaceRef("provider", "surface", "1.0"),
        identity=SessionIdentityCapabilities(),
        content=ContentStreamCapabilities(channels=channels),
        validation=SurfaceValidation(
            evidence=ValidationEvidence(
                validated=validated,
                reference="tests/unit/agents/test_agents_gateway_output.py" if validated else "",
            ),
        ),
    )


def _event(*, sequence: int = 1) -> AgentOutputEvent:
    return AgentOutputEvent(
        session_id="session",
        turn_id="turn",
        sequence=sequence,
        kind=AgentOutputKind.ASSISTANT_TEXT_DELTA,
        text="hello",
        observed_at="2026-08-03T00:00:00Z",
        is_final=False,
    )


@pytest.mark.asyncio
async def test_relay_persists_when_resolved_surface_authorizes_assistant_text(tmp_path: Path) -> None:
    surface = _surface(
        validated=True,
        channels=(ContentChannelCapability(ContentChannelId.ASSISTANT_TEXT, 1024, 10),),
    )
    relay = create_relay(
        tmp_path, "request", "session", "turn", OutputPolicy.default_enabled(), surface=surface
    )

    await relay(_event())

    assert relay.has_events
    assert read_request_output(tmp_path, "request")["events"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_relay_rejects_unvalidated_surface_without_persisting(tmp_path: Path) -> None:
    surface = _surface(validated=False, channels=())
    relay = create_relay(
        tmp_path, "request", "session", "turn", OutputPolicy.default_enabled(), surface=surface
    )

    await relay(_event())

    assert not relay.has_events
    assert read_request_output(tmp_path, "request")["events"] == []


@pytest.mark.asyncio
async def test_relay_rejects_surface_without_assistant_text_channel(tmp_path: Path) -> None:
    surface = _surface(
        validated=True,
        channels=(ContentChannelCapability(ContentChannelId.ASSISTANT_FINAL, 1024, 10),),
    )
    relay = create_relay(
        tmp_path, "request", "session", "turn", OutputPolicy.default_enabled(), surface=surface
    )

    await relay(_event())

    assert not relay.has_events
    assert read_request_output(tmp_path, "request")["events"] == []
