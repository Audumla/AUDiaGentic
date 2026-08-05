"""Unit tests for the gpt-auto CDP session transport (BR04).

These tests drive GptAutoSessionTransport with a scripted fake CdpClient — no
real browser, no bot-detection risk. They cover the AgentSessionTransport
protocol mapping: open/resume, prompt/end-turn, cancellation, control
dispositions, and idempotent close.

The live probe (test_session_transport_live.py) is the AS29 evidence reference
and is intentionally NOT exercised by this file.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from audiagentic.components.providers.adapters.gpt_auto import session_transport
from audiagentic.components.providers.adapters.gpt_auto.cdp_client import TabInfo
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
    build_gpt_auto_session_transport,
)
from audiagentic.components.providers.adapters.gpt_auto.tab_state import update_mapping
from audiagentic.foundation.transports.agent_session import (
    ControlDisposition,
    SessionControlAction,
    SessionControlRequest,
    SessionOpenResult,
    SessionPrompt,
    SessionTurnResult,
)

PROJECT_NAME = "test-project"
WORKSPACE_URL = "https://chatgpt.com/g/g-p-abc-def"
PROJECT_URL = f"{WORKSPACE_URL}/project"
CONVERSATION_ID = "conv123"
CONVERSATION_URL = f"{WORKSPACE_URL}/c/{CONVERSATION_ID}"

FAST_CONFIG = GptAutoConfig(
    tab_selection_timeout=5.0,
    login_timeout=5.0,
    response_wait_timeout=5.0,
    polling_interval=0.05,
    typing_speed=0.0,
)


class FakeCdpClient:
    """Scripted CdpClient stand-in keyed on the known JS snippets."""

    def __init__(self, *, workspace_url: str = PROJECT_URL) -> None:
        self.workspace_url = workspace_url
        self.active_url = "https://chatgpt.com"
        self.started = False
        self.stopped = False
        self.submit_count = 0
        self.response_text: str | None = None
        self.generating = False
        self.stop_clicked = 0
        self.calls: list[str] = []

    # -- lifecycle --
    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    # -- tab operations --
    async def get_url(self) -> str:
        return self.active_url

    async def new_tab(self, url: str) -> TabInfo:
        self.active_url = url
        return TabInfo(url=url, title="", tab_id="t-new")

    async def activate_tab(self, tab_id: str) -> TabInfo | None:
        self.active_url = self.workspace_url
        return TabInfo(url=self.active_url, title="", tab_id=tab_id)

    async def mouse_click(self, x: int, y: int) -> None:
        self.active_url = self.workspace_url

    # -- DOM evaluation, scripted on distinctive JS substrings --
    async def evaluate(self, script: str, *args) -> object:
        self.calls.append(script)
        s = script
        if "window.location.href" in s:
            match = re.search(r'"(https?://[^"]+)"', s)
            if match:
                self.active_url = match.group(1)
            return True
        if 'input[type="email"]' in s:
            return "unknown"
        if "Welcome back" in s and 'data-testid="login-button"' in s:
            return True
        if "getBoundingClientRect" in s:
            return {"name": PROJECT_NAME, "centerX": 100, "centerY": 200}
        if "buttonLabel" in s:
            self.submit_count += 1
            return {"submitted": True, "textLength": 10}
        if "beforeinput" in s:
            return {"ok": True, "textLength": 10}
        if "innerHTML = ''" in s:
            return {"ok": True}
        if "result-streaming" in s:
            return self.generating
        if "btn.click()" in s and "stop-generating" in s:
            self.stop_clicked += 1
            return True
        if "data-message-author-role" in s:
            if "count" in s:
                return {"count": self.submit_count, "text": self.response_text}
            return self.response_text
        return True


def _make_transport(
    tmp_path,
    *,
    fake: FakeCdpClient | None = None,
    resume_provider_ref: str | None = None,
    project_name: str = PROJECT_NAME,
    config: GptAutoConfig = FAST_CONFIG,
) -> tuple[GptAutoSessionTransport, FakeCdpClient]:
    fake = fake or FakeCdpClient()
    transport = GptAutoSessionTransport(
        tmp_path,
        config=config,
        project_name=project_name,
        resume_provider_ref=resume_provider_ref,
        client_factory=lambda url: fake,
    )
    return transport, fake


def _seed_mapping(
    tmp_path,
    *,
    workspace_url: str = WORKSPACE_URL,
    conversation_id: str = "",
) -> None:
    update_mapping(
        PROJECT_NAME,
        tab_id="t1",
        workspace_url=workspace_url,
        conversation_id=conversation_id,
        project_root=tmp_path,
    )


async def _collect_sink(observations):
    collected = []

    async def _sink(obs):
        collected.append(obs)

    return _sink, collected


# ── open / resume ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_str_is_bare_ref(tmp_path):
    """str(open()) is the provider-session-ref persisted by the gateway (AS30)."""
    _seed_mapping(tmp_path)
    transport, fake = _make_transport(tmp_path)

    result = await transport.open()

    assert isinstance(result, SessionOpenResult)
    assert str(result) == WORKSPACE_URL
    assert fake.started
    assert transport.is_alive()


@pytest.mark.asyncio
async def test_resume_conversation_returns_conversation_id(tmp_path):
    _seed_mapping(tmp_path, conversation_id=CONVERSATION_ID)
    fake = FakeCdpClient(workspace_url=CONVERSATION_URL)
    transport, _ = _make_transport(tmp_path, fake=fake, resume_provider_ref=CONVERSATION_ID)

    result = await transport.open()

    assert str(result) == CONVERSATION_ID


@pytest.mark.asyncio
async def test_resume_by_workspace_base_url(tmp_path):
    _seed_mapping(tmp_path, conversation_id=CONVERSATION_ID)
    fake = FakeCdpClient(workspace_url=WORKSPACE_URL)
    transport, _ = _make_transport(tmp_path, fake=fake, resume_provider_ref=WORKSPACE_URL)

    result = await transport.open()

    assert str(result) == WORKSPACE_URL


@pytest.mark.asyncio
async def test_open_result_str_is_bare_ref():
    """The __str__ override must yield the bare ref, never the dataclass repr."""
    result = session_transport._GptAutoOpenResult(ag_session_id=CONVERSATION_ID)
    assert isinstance(result, SessionOpenResult)
    assert str(result) == CONVERSATION_ID


# ── prompt / end-turn ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_end_turn_returns_final_summary(tmp_path, monkeypatch):
    _seed_mapping(tmp_path)
    transport, fake = _make_transport(tmp_path)
    await transport.open()

    async def _fake_inject(client, prompt, **kwargs):
        client.submit_count += 1
        client.response_text = "response 1"

    monkeypatch.setattr(session_transport, "inject_prompt", _fake_inject)
    sink, collected = await _collect_sink(None)

    result = await transport.prompt(
        SessionPrompt(turn_id="turn-1", body="hello"),
        sink,
    )

    assert isinstance(result, SessionTurnResult)
    assert result.stop_reason == "end_turn"
    assert result.final_summary == "response 1"
    assert fake.submit_count == 1
    kinds = {obs.kind.value for obs in collected}
    assert "turn-accepted" in kinds
    assert "activity" in kinds
    assert "terminal" in kinds


@pytest.mark.asyncio
async def test_prompt_precancelled_returns_cancelled(tmp_path, monkeypatch):
    _seed_mapping(tmp_path)
    transport, fake = _make_transport(tmp_path)
    await transport.open()

    monkeypatch.setattr(
        session_transport, "inject_prompt", lambda *a, **k: _unreachable()
    )
    cancel_token = asyncio.Event()
    cancel_token.set()
    sink, _ = await _collect_sink(None)

    result = await transport.prompt(
        SessionPrompt(turn_id="turn-1", body="hello", cancel_token=cancel_token),
        sink,
    )

    assert result.stop_reason == "cancelled"
    assert result.observations_delivered == 1


async def _unreachable():  # pragma: no cover — must never be called
    raise AssertionError("inject_prompt must not run for a pre-cancelled turn")


@pytest.mark.asyncio
async def test_prompt_mid_turn_cancel_stops_generation(tmp_path, monkeypatch):
    _seed_mapping(tmp_path)
    transport, fake = _make_transport(tmp_path)
    await transport.open()

    async def _fake_inject_slow(client, prompt, **kwargs):
        client.submit_count += 1
        client.response_text = None
        client.generating = True

    monkeypatch.setattr(session_transport, "inject_prompt", _fake_inject_slow)
    sink, _ = await _collect_sink(None)

    prompt_task = asyncio.create_task(
        transport.prompt(SessionPrompt(turn_id="turn-1", body="hello"), sink)
    )
    await asyncio.sleep(0.1)
    control_result = await transport.control(
        SessionControlRequest(
            ag_session_id="sess",
            turn_id="turn-1",
            action=SessionControlAction.CANCEL_TURN,
        )
    )
    result = await prompt_task

    assert control_result.disposition == ControlDisposition.ACCEPTED
    assert result.stop_reason == "cancelled"
    assert fake.stop_clicked >= 1


@pytest.mark.asyncio
async def test_prompt_timeout_returns_error(tmp_path, monkeypatch):
    _seed_mapping(tmp_path)
    transport, fake = _make_transport(tmp_path)
    await transport.open()

    async def _fake_inject_no_response(client, prompt, **kwargs):
        client.submit_count += 1
        client.response_text = None
        client.generating = False

    monkeypatch.setattr(session_transport, "inject_prompt", _fake_inject_no_response)
    sink, _ = await _collect_sink(None)

    result = await transport.prompt(
        SessionPrompt(turn_id="turn-1", body="hello"),
        sink,
    )

    assert result.stop_reason == "error"
    assert result.final_summary is None


# ── control dispositions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_control_unsupported_actions(tmp_path):
    transport, _ = _make_transport(tmp_path)

    cases = (
        (SessionControlAction.INTERRUPT_TURN, {}),
        (SessionControlAction.STEER_TURN, {"steer_text": "slow down"}),
        (SessionControlAction.RESPOND_PERMISSION, {"permission": "allow"}),
    )
    for action, payload in cases:
        result = await transport.control(
            SessionControlRequest(
                ag_session_id="sess", turn_id="t", action=action, payload=payload
            )
        )
        assert result.disposition == ControlDisposition.UNSUPPORTED


@pytest.mark.asyncio
async def test_control_cancel_when_not_alive(tmp_path):
    transport, _ = _make_transport(tmp_path)

    result = await transport.control(
        SessionControlRequest(
            ag_session_id="sess", turn_id="t", action=SessionControlAction.CANCEL_TURN
        )
    )

    assert result.disposition == ControlDisposition.UNSUPPORTED


@pytest.mark.asyncio
async def test_control_close_session(tmp_path):
    _seed_mapping(tmp_path)
    transport, fake = _make_transport(tmp_path)
    await transport.open()

    result = await transport.control(
        SessionControlRequest(
            ag_session_id="sess", turn_id="t", action=SessionControlAction.CLOSE_SESSION
        )
    )

    assert result.disposition == ControlDisposition.ACCEPTED
    assert fake.stopped
    assert not transport.is_alive()


# ── close / alive ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_idempotent_and_detaches_without_closing_tab(tmp_path):
    _seed_mapping(tmp_path)
    transport, fake = _make_transport(tmp_path)
    await transport.open()
    assert transport.is_alive()

    await transport.close()
    await transport.close()  # second close must be a no-op

    assert fake.stopped
    assert not transport.is_alive()


# ── factory ──────────────────────────────────────────────────────────


def test_build_factory_returns_transport(tmp_path):
    transport = build_gpt_auto_session_transport(tmp_path, config={})

    assert isinstance(transport, GptAutoSessionTransport)
    assert not transport.is_alive()
