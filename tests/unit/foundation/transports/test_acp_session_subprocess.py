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

# ACP transport requires the optional `audiagentic[acp]` extra; skip when missing.
pytest.importorskip("acp", reason="ACP transport dependency not installed")

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
            raise AssertionError(f"Child process {child_pid} still alive after close() — orphan!")
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


@pytest.mark.asyncio
@pytest.mark.timeout(_SUBPROCESS_TIMEOUT)
async def test_intra_turn_event_ordering_model_tool_model(tmp_path):
    """Intra-turn events follow the correct model → tool → result sequence.

    The fake ACP agent emits normalized events using ACP SDK types:
    AgentThoughtChunk (model starting) -> AgentMessageChunk (response)
    -> ToolCallProgress pending (tool started) -> ToolCallProgress completed (tool done)
    -> result (terminal)

    This proves AS18/AS20 can rely on event ordering for concurrency decisions.
    The ACP SDK produces sessionUpdate values: agent_thought_chunk,
    agent_message_chunk, tool_call_update — the transport normalizes these to
    the CANONICAL vocabulary (thought, assistant-message, tool-call) with the
    raw wire kind preserved in ext (RV679: raw kinds must not leak as event
    kinds — turn-state consumers key on canonical kinds only).
    """
    launch = AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,))
    transport = AcpSessionTransport(launch, cwd=tmp_path)

    try:
        await transport.open()
        result = await transport.prompt("hello")

        kinds = [e.kind for e in result.events]

        # Verify the canonical sequence exists in order
        expected_sequence = ["thought", "assistant-message", "tool-call", "tool-call", "result"]
        assert expected_sequence == kinds, f"event ordering incorrect: got {kinds}"

        # Verify thought (model starting) is not terminal and keeps raw kind
        started_event = result.events[0]
        assert started_event.kind == "thought"
        assert started_event.ext["acp"]["raw_kind"] == "agent_thought_chunk"
        assert not started_event.terminal, "thought should not be terminal"

        # Verify tool-call events carry status in ext (compact-safe location)
        tool_started = result.events[2]
        assert tool_started.kind == "tool-call"
        assert tool_started.ext["acp"]["raw_kind"] == "tool_call_update"
        assert not tool_started.terminal
        assert tool_started.ext["acp"].get("status") in ("pending", "in_progress"), (
            f"tool-call missing status: {tool_started.ext}"
        )

        tool_completed = result.events[3]
        assert tool_completed.kind == "tool-call"
        assert tool_completed.ext["acp"].get("status") == "completed"
        assert not tool_completed.terminal

        # Verify terminal result event exists
        result_events = [e for e in result.events if e.terminal]
        assert len(result_events) > 0, "no terminal result event"
        assert result_events[0].kind == "result", (
            f"terminal event should be 'result', got {result_events[0].kind}"
        )
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.timeout(_SUBPROCESS_TIMEOUT)
async def test_write_read_terminal_are_real_over_the_live_acp_wire(tmp_path):
    """AS68: the fake agent drives write_text_file/read_text_file/
    create_terminal/wait_for_terminal_exit/terminal_output/release_terminal
    for real over a live subprocess — not mocked at any layer. The agent
    reports success via its final assistant message once it has itself
    verified the round trip, so this test only needs to check that message
    plus the file this client's write_text_file implementation actually put
    on disk."""
    launch = AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,))
    transport = AcpSessionTransport(launch, cwd=tmp_path)

    try:
        await transport.open()
        result = await transport.prompt("test-fs-terminal")

        texts = [e.text for e in result.events if e.kind == "assistant-message"]
        assert texts == ["AS68_OK"], f"fs/terminal round trip failed: events={result.events}"
        assert (tmp_path / "as68_proof.txt").read_text(encoding="utf-8") == "AS68_FS_PROOF"
    finally:
        await transport.close()
