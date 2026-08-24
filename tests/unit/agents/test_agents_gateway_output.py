"""AS31 OutputRelay capability authorization tests."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import gateway_final_response_path
from audiagentic.components.agents.gateway.output import (
    OutputPolicy,
    create_relay,
    persist_final_response,
    read_final_response,
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


def test_final_response_artifact_hashes_exact_utf8_bytes(tmp_path: Path) -> None:
    text = "line one\nβeta\n" * 700
    artifact = persist_final_response(tmp_path, "request", text)
    raw = gateway_final_response_path(tmp_path, "request").read_bytes()

    assert raw == text.encode("utf-8")
    assert artifact["bytes"] == len(raw)
    assert artifact["sha256"] == hashlib.sha256(raw).hexdigest()
    assert read_final_response(tmp_path, "request", artifact) == text
