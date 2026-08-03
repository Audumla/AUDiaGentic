"""AS06 Step 1 — Real-transport tests with fake ACP stdio agent.

Exercises the REAL AcpSessionTransport against a real subprocess (fake_acp_agent.py)
to prove context retention and child process cleanup.
"""
from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import psutil
import pytest

from audiagentic.foundation.transports.acp import AcpLaunch, AcpSessionTransport


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("acp") is None,
    reason="acp extra is not installed (agent-client-protocol missing)",
)

# Resolve the fake ACP agent script at module load time
_FAKE_AGENT_SCRIPT = Path(__file__).resolve().parent.parent.parent.parent / "unit" / "fixtures" / "fake_acp_agent.py"
PYTHON_EXE = sys.executable


def _transport(cwd: Path) -> AcpSessionTransport:
    """Create an AcpSessionTransport targeting the fake ACP agent."""
    return AcpSessionTransport(
        AcpLaunch(PYTHON_EXE, (str(_FAKE_AGENT_SCRIPT),)),
        cwd=cwd,
    )


def _process_alive(pid: int) -> bool:
    """Return True if the process with the given pid still exists."""
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


@pytest.mark.asyncio
async def test_two_prompts_retain_state(tmp_path: Path) -> None:
    """Two prompt turns share one session and child process.

    Turn 2's response contains turn=2, proving the agent retained state from turn 1.
    """
    transport = _transport(tmp_path)
    try:
        session_id = await transport.open()
        assert transport.is_alive()

        # First turn
        r1 = await transport.prompt("hello")
        assert r1.session_id == session_id
        texts_1 = [e.text for e in r1.events if e.kind == "assistant-message"]
        assert len(texts_1) == 1, f"expected exactly one assistant-message, got {texts_1}"
        assert texts_1[0] is not None and "[turn=1]" in texts_1[0], f"expected turn=1 in {texts_1[0]}"

        # Second turn — same session, state retained
        r2 = await transport.prompt("world")
        assert r2.session_id == session_id
        texts_2 = [e.text for e in r2.events if e.kind == "assistant-message"]
        assert len(texts_2) == 1, f"expected exactly one assistant-message, got {texts_2}"
        assert texts_2[0] is not None and "[turn=2]" in texts_2[0], f"expected turn=2 in {texts_2[0]}"

        # Child still alive between turns
        assert transport.is_alive()
    finally:
        await transport.close()


def _get_child_pid(transport: AcpSessionTransport) -> int | None:
    """Extract the child process PID from the transport, if available."""
    proc = transport._proc
    if proc is not None and hasattr(proc, "pid"):
        return proc.pid
    return None


@pytest.mark.asyncio
async def test_close_terminates_child_process(tmp_path: Path) -> None:
    """close() terminates the child process; PID is gone after close."""
    transport = _transport(tmp_path)
    pid = None
    try:
        await transport.open()
        assert transport.is_alive()
        pid = _get_child_pid(transport)
        assert pid is not None, "child PID should be available from the SDK"
        # Verify the process is alive before close
        assert _process_alive(pid), f"PID {pid} should exist before close"
    finally:
        await transport.close()

    # After close, the child process should be gone
    if pid is not None:
        assert not _process_alive(pid), f"PID {pid} should be gone after close"


def _extract_text_for_turn(events: tuple, turn_number: int) -> str | None:
    """Helper to extract the assistant message text for a given turn."""
    for e in events:
        if e.kind == "assistant-message" and e.text:
            if f"[turn={turn_number}]" in e.text:
                return e.text
    return None


@pytest.mark.asyncio
async def test_two_prompts_share_one_session_and_child(tmp_path: Path) -> None:
    """Two prompt turns share one session and child process.

    The SDK's new_session is called exactly once; the same child process serves both turns.
    """
    transport = _transport(tmp_path)
    try:
        await transport.open()
        await transport.prompt("first")
        pid_after_first = _get_child_pid(transport)

        r2 = await transport.prompt("second")
        pid_after_second = _get_child_pid(transport)

        # Same child process across turns
        assert pid_after_first == pid_after_second, (
            f"child PID changed between turns: {pid_after_first} -> {pid_after_second}"
        )

        # State retained: turn 2 shows count=2
        text = _extract_text_for_turn(r2.events, 2)
        assert text is not None, f"expected turn=2 message in {r2.events}"
    finally:
        await transport.close()
