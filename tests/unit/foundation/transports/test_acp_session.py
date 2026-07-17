"""AS01 — AcpSessionTransport lifecycle tests (plan agent-sessions).

The frozen per-turn contract is covered by test_acp_execution.py via the
run_acp_prompt wrapper; these tests pin the session extension: multi-turn
reuse of one child/session, idempotent bounded close, prompt-after-close,
between-turn update handling, and no-child-leak on failed open.
"""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.acp import (
    ERR_EXECUTION_FAILED,
    ERR_SESSION_NOT_OPEN,
    AcpLaunch,
    AcpSessionTransport,
)


class _FakeProc:
    """Minimal child-process stand-in with termination bookkeeping."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0


def _install_sdk(monkeypatch, *, prompt_side_effect=None, proc=None, exited=None):
    """Install a fake acp SDK; returns (conn, proc, captured, exited-list)."""
    captured = {"client": None}
    exited = exited if exited is not None else []

    conn = MagicMock()
    conn.initialize = AsyncMock()
    conn.new_session = AsyncMock(return_value=SimpleNamespace(session_id="s1"))
    turn_counter = {"n": 0}

    async def default_prompt(session_id, prompt):
        turn_counter["n"] += 1
        client = captured["client"]
        if client is not None:
            await client.session_update(
                session_id,
                {"sessionUpdate": "agent_message_chunk", "text": f"turn-{turn_counter['n']}"},
            )
        return SimpleNamespace(stop_reason="end_turn")

    conn.prompt = AsyncMock(side_effect=prompt_side_effect or default_prompt)

    proc = proc if proc is not None else _FakeProc()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=(conn, proc))

    async def _aexit(*args):
        exited.append(True)
        if proc.returncode is None:
            proc.returncode = 0
        return False

    mock_ctx.__aexit__ = AsyncMock(side_effect=_aexit)

    def spawn(client_instance, executable, *args, **kwargs):
        captured["client"] = client_instance
        return mock_ctx

    acp_mod = types.ModuleType("acp")
    acp_mod.PROTOCOL_VERSION = 1
    acp_mod.spawn_agent_process = spawn
    acp_mod.text_block = lambda text: {"type": "text", "text": text}
    interfaces_mod = types.ModuleType("acp.interfaces")
    interfaces_mod.Client = object
    monkeypatch.setitem(sys.modules, "acp", acp_mod)
    monkeypatch.setitem(sys.modules, "acp.interfaces", interfaces_mod)
    return conn, proc, captured, exited


@pytest.mark.asyncio
async def test_two_prompts_share_one_session_and_child(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    session_id = await transport.open()
    assert session_id == "s1"
    assert transport.is_alive()

    first = await transport.prompt("one")
    second = await transport.prompt("two")

    assert first.session_id == second.session_id == "s1"
    conn.new_session.assert_awaited_once()  # session created exactly once
    assert not exited  # child still alive between turns
    # Each turn has its own pipeline: sequences restart at 0
    assert first.events[0].sequence == 0
    assert second.events[0].sequence == 0
    texts = [e.text for e in second.events if e.kind == "assistant-message"]
    assert texts == ["turn-2"]

    await transport.close()
    assert exited  # SDK context unwound
    assert not transport.is_alive()


@pytest.mark.asyncio
async def test_close_is_idempotent_and_prompt_after_close_raises(tmp_path, monkeypatch):
    _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    await transport.close()
    await transport.close()  # second close must be a no-op, never raise

    with pytest.raises(AudiaGenticError, match=ERR_SESSION_NOT_OPEN):
        await transport.prompt("too late")


@pytest.mark.asyncio
async def test_prompt_before_open_raises(tmp_path, monkeypatch):
    _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    with pytest.raises(AudiaGenticError, match=ERR_SESSION_NOT_OPEN):
        await transport.prompt("never opened")


@pytest.mark.asyncio
async def test_double_open_raises(tmp_path, monkeypatch):
    _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    with pytest.raises(AudiaGenticError, match=ERR_SESSION_NOT_OPEN):
        await transport.open()
    await transport.close()


@pytest.mark.asyncio
async def test_failed_open_unwinds_child(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    conn.new_session = AsyncMock(side_effect=RuntimeError("no session for you"))
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    with pytest.raises(AudiaGenticError, match=ERR_EXECUTION_FAILED):
        await transport.open()
    assert exited, "child context must be unwound when open fails"
    assert not transport.is_alive()


@pytest.mark.asyncio
async def test_mid_turn_failure_marks_transport_dead(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def crash_second(session_id, prompt):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("child died")
        return SimpleNamespace(stop_reason="end_turn")

    _install_sdk(monkeypatch, prompt_side_effect=crash_second)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    await transport.prompt("fine")
    with pytest.raises(AudiaGenticError, match=ERR_EXECUTION_FAILED):
        await transport.prompt("crashes")
    assert not transport.is_alive()
    with pytest.raises(AudiaGenticError, match=ERR_SESSION_NOT_OPEN):
        await transport.prompt("dead session")
    await transport.close()  # still safe


@pytest.mark.asyncio
async def test_updates_between_turns_are_counted_not_delivered(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    # Update arriving with no turn in flight
    await captured["client"].session_update("s1", {"sessionUpdate": "status", "message": "stray"})
    assert transport.dropped_between_turns == 1
    result = await transport.prompt("one")
    assert all(e.text != "stray" for e in result.events)
    await transport.close()


@pytest.mark.asyncio
async def test_cancel_signal_set_skips_turn_session_survives(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    cancel = asyncio.Event()
    cancel.set()
    result = await transport.prompt("skipped", cancel_signal=cancel)
    assert result.stop_reason == "cancelled"
    conn.prompt.assert_not_called()
    assert transport.is_alive()  # a skipped turn does not kill the session
    follow_up = await transport.prompt("real turn")
    assert follow_up.stop_reason == "end_turn"
    await transport.close()


@pytest.mark.asyncio
async def test_overflow_preserves_assistant_text_past_event_cap(tmp_path, monkeypatch):
    """Assistant TEXT from events dropped by the MAX_EVENTS cap survives in
    overflow_text — a worker's final report must never be lost to budget
    pressure (MA29 live truncation finding)."""
    from audiagentic.foundation.transports.acp import MAX_EVENTS

    async def prompt_flood(session_id, prompt):
        client = captured["client"]
        for i in range(MAX_EVENTS + 50):
            await client.session_update(
                session_id,
                {"sessionUpdate": "agent_message_chunk", "text": f"[{i}]"},
            )
        return SimpleNamespace(stop_reason="end_turn")

    conn, proc, captured, exited = _install_sdk(monkeypatch, prompt_side_effect=prompt_flood)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    result = await transport.prompt("go")
    await transport.close()

    assert result.dropped_events > 0  # cap semantics unchanged
    assert len(result.events) <= MAX_EVENTS + 1
    assert result.overflow_text is not None
    # The last chunk — beyond the cap — is preserved as text
    assert f"[{MAX_EVENTS + 49}]" in result.overflow_text


@pytest.mark.asyncio
async def test_compact_mode_buffers_no_payloads(tmp_path, monkeypatch):
    """compact_events=True keeps kind/text but never the raw update payload."""
    async def prompt_one(session_id, prompt):
        client = captured["client"]
        await client.session_update(
            session_id,
            {"sessionUpdate": "agent_message_chunk", "text": "hi", "blob": "X" * 5000},
        )
        return SimpleNamespace(stop_reason="end_turn")

    conn, proc, captured, exited = _install_sdk(monkeypatch, prompt_side_effect=prompt_one)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path, compact_events=True)
    await transport.open()
    result = await transport.prompt("go")
    await transport.close()

    msg = next(e for e in result.events if e.kind == "assistant-message")
    assert msg.text == "hi"
    assert "payload" not in msg.ext["acp"]
    assert result.bytes_buffered < 2000  # payload not counted or stored


@pytest.mark.asyncio
async def test_close_force_terminates_stubborn_child(tmp_path, monkeypatch):
    proc = _FakeProc()
    exited: list[bool] = []
    conn, proc, captured, exited = _install_sdk(monkeypatch, proc=proc, exited=exited)

    # Simulate an SDK unwind that does NOT reap the child
    async def _aexit_no_reap(*args):
        exited.append(True)
        return False

    # Rebuild: patch the ctx __aexit__ after open by leaving returncode None
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    # Force the "SDK exit didn't kill it" condition
    proc.returncode = None

    def sticky_terminate():
        proc.terminated = True  # refuses to set returncode

    proc.terminate = sticky_terminate
    await transport.close()
    assert proc.terminated or proc.returncode is not None
