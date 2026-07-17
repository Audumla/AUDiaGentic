"""AS06 — Real-subprocess AcpSessionTransport tests (plan agent-sessions).

Drives AcpSessionTransport against a real child process (fake_acp_agent.py)
with no mocks. Proves context retention across turns and the no-orphan
guarantee after close.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.acp import (
    ERR_SESSION_NOT_OPEN,
    AcpLaunch,
    AcpSessionTransport,
)

_FAKE_AGENT = str(Path(__file__).parent / "fixtures" / "fake_acp_agent.py")

# 30 s is generous: spawn + initialize + new_session + prompt round-trip
_SUBPROCESS_TIMEOUT = 30


@pytest.mark.asyncio
@pytest.mark.timeout(_SUBPROCESS_TIMEOUT)
async def test_two_prompts_retain_context_in_one_process(tmp_path):
    """Two turns on the same transport share one child and one session.

    The second turn's assistant text must be 'turn-2', proving state was
    retained in the live process.
    """
    launch = AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,))
    transport = AcpSessionTransport(launch, cwd=tmp_path)

    try:
        session_id = await transport.open()
        assert session_id is not None

        first = await transport.prompt("hello")
        second = await transport.prompt("world")

        assert first.session_id == second.session_id == session_id

        texts_1 = [e.text for e in first.events if e.kind == "assistant-message"]
        texts_2 = [e.text for e in second.events if e.kind == "assistant-message"]

        assert texts_1 == ["turn-1"]
        assert texts_2 == ["turn-2"], "context not retained across turns"

        assert first.stop_reason == "end_turn"
        assert second.stop_reason == "end_turn"
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.timeout(_SUBPROCESS_TIMEOUT)
async def test_close_kills_child_process_no_orphan(tmp_path):
    """After close(), the child process must no longer exist.

    The fake agent embeds its PID in the session id (format 'fake-<pid>').
    We extract that PID and verify it is dead after close().
    """
    launch = AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,))
    transport = AcpSessionTransport(launch, cwd=tmp_path)

    child_pid = None
    try:
        session_id = await transport.open()
        assert session_id.startswith("fake-")

        child_pid = int(session_id.split("-", 1)[1])
        assert os.getpid() != child_pid

        await transport.prompt("hello")

        await transport.close()

        # No-orphan proof: the child PID must be gone
        # On Windows, os.kill(pid, 0) raises OSError for a dead pid instead of
        # ProcessLookupError; we catch both.
        try:
            os.kill(child_pid, 0)
            raise AssertionError(
                f"Child process {child_pid} still alive after close() — orphan!"
            )
        except (ProcessLookupError, OSError):
            pass  # expected: process is dead
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.timeout(_SUBPROCESS_TIMEOUT)
async def test_prompt_after_close_raises_CON_ACP_001(tmp_path):
    """A prompt() on a closed transport raises CON-ACP-001."""
    launch = AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,))
    transport = AcpSessionTransport(launch, cwd=tmp_path)

    try:
        await transport.open()
        await transport.prompt("hello")
        await transport.close()

        with pytest.raises(AudiaGenticError, match=ERR_SESSION_NOT_OPEN):
            await transport.prompt("too late")
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.timeout(_SUBPROCESS_TIMEOUT)
async def test_is_alive_reflects_lifecycle(tmp_path):
    """is_alive() tracks the transport state through open/close."""
    launch = AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,))
    transport = AcpSessionTransport(launch, cwd=tmp_path)

    try:
        assert not transport.is_alive(), "dead before open"

        await transport.open()
        assert transport.is_alive(), "not alive after open"

        await transport.prompt("hello")
        assert transport.is_alive(), "not alive during use"

        await transport.close()
        assert not transport.is_alive(), "alive after close"
    finally:
        await transport.close()
