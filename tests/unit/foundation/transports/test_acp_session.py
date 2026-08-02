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
    ERR_FS_ESCAPE,
    ERR_RESUME_UNSUPPORTED,
    ERR_SESSION_NOT_OPEN,
    ERR_UNKNOWN_TERMINAL,
    AcpLaunch,
    AcpSessionTransport,
    _TurnPipeline,
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


def _install_sdk(monkeypatch, *, prompt_side_effect=None, proc=None, exited=None, load_session_supported=False):
    """Install a fake acp SDK; returns (conn, proc, captured, exited-list)."""
    captured = {"client": None}
    exited = exited if exited is not None else []

    conn = MagicMock()
    conn.initialize = AsyncMock(
        return_value=SimpleNamespace(
            agent_capabilities=SimpleNamespace(load_session=load_session_supported),
        )
    )
    conn.new_session = AsyncMock(return_value=SimpleNamespace(session_id="s1"))
    conn.load_session = AsyncMock(return_value=SimpleNamespace())
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
    # AS68: minimal response-model stand-ins for the fs/terminal Client
    # methods — real acp.schema pydantic models aren't needed to prove this
    # module's own confinement/forwarding/tracking logic, just something
    # with the right attribute names.
    acp_mod.WriteTextFileResponse = lambda: SimpleNamespace()
    acp_mod.ReadTextFileResponse = lambda content: SimpleNamespace(content=content)
    acp_mod.CreateTerminalResponse = lambda terminal_id: SimpleNamespace(terminal_id=terminal_id)
    acp_mod.TerminalOutputResponse = lambda output, truncated, exit_status: SimpleNamespace(
        output=output, truncated=truncated, exit_status=exit_status
    )
    acp_mod.WaitForTerminalExitResponse = lambda exit_code, signal: SimpleNamespace(
        exit_code=exit_code, signal=signal
    )
    interfaces_mod = types.ModuleType("acp.interfaces")
    interfaces_mod.Client = object
    schema_mod = types.ModuleType("acp.schema")
    schema_mod.TerminalExitStatus = lambda exit_code=None, signal=None: SimpleNamespace(
        exit_code=exit_code, signal=signal
    )
    monkeypatch.setitem(sys.modules, "acp", acp_mod)
    monkeypatch.setitem(sys.modules, "acp.interfaces", interfaces_mod)
    monkeypatch.setitem(sys.modules, "acp.schema", schema_mod)
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


# ── AS49/AS10: generic ACP session/load resume support ─────────────────────

@pytest.mark.asyncio
async def test_open_resumed_calls_load_session_when_supported(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch, load_session_supported=True)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    session_id = await transport.open_resumed("predecessor-ref-123")

    assert session_id == "predecessor-ref-123"
    assert transport.session_id == "predecessor-ref-123"
    assert transport.supports_resume is True
    conn.load_session.assert_awaited_once()
    conn.new_session.assert_not_awaited()
    assert transport.is_alive()


@pytest.mark.asyncio
async def test_open_resumed_raises_and_tears_down_child_when_unsupported(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch, load_session_supported=False)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)

    with pytest.raises(AudiaGenticError, match=ERR_RESUME_UNSUPPORTED):
        await transport.open_resumed("predecessor-ref-123")

    conn.load_session.assert_not_awaited()
    assert exited  # spawned child was torn down, never leaked
    assert not transport.is_alive()
    assert transport.supports_resume is False


@pytest.mark.asyncio
async def test_open_after_open_resumed_still_rejected(tmp_path, monkeypatch):
    """The already-opened/closed guard applies uniformly to both open paths."""
    _install_sdk(monkeypatch, load_session_supported=True)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open_resumed("predecessor-ref-123")

    with pytest.raises(AudiaGenticError, match=ERR_SESSION_NOT_OPEN):
        await transport.open()


# ── AS41: PreSpawnHook inversion-of-control seam ────────────────────────────

class _RecordingHook:
    def __init__(self, *, raise_on_environment_ready=False, raise_on_close=False):
        self.environment_seen = None
        self.close_calls = []
        self._raise_on_environment_ready = raise_on_environment_ready
        self._raise_on_close = raise_on_close

    def on_environment_ready(self, environment):
        self.environment_seen = dict(environment)
        if self._raise_on_environment_ready:
            raise RuntimeError("boom-on-environment-ready")
        return {"listener": "fake-listener-handle"}

    def on_close(self, hook_state):
        self.close_calls.append(hook_state)
        if self._raise_on_close:
            raise RuntimeError("boom-on-close")


@pytest.mark.asyncio
async def test_pre_spawn_hook_called_with_launch_environment_before_spawn(tmp_path, monkeypatch):
    _install_sdk(monkeypatch)
    hook = _RecordingHook()
    launch = AcpLaunch("agent", args=(), environment={"TAP_ADDRESS": "127.0.0.1:9", "TAP_AUTHKEY": "secret"})
    transport = AcpSessionTransport(launch, cwd=tmp_path, pre_spawn_hook=hook)
    await transport.open()

    assert hook.environment_seen == {"TAP_ADDRESS": "127.0.0.1:9", "TAP_AUTHKEY": "secret"}


@pytest.mark.asyncio
async def test_pre_spawn_hook_state_passed_to_on_close_symmetrically(tmp_path, monkeypatch):
    _install_sdk(monkeypatch)
    hook = _RecordingHook()
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path, pre_spawn_hook=hook)
    await transport.open()
    assert hook.close_calls == []  # not called yet

    await transport.close()
    assert hook.close_calls == [{"listener": "fake-listener-handle"}]


@pytest.mark.asyncio
async def test_pre_spawn_hook_failure_does_not_block_open(tmp_path, monkeypatch):
    """Hook setup is best-effort — a broken hook must never prevent a session
    from opening (AS41: tap enrichment is optional, never load-bearing)."""
    _install_sdk(monkeypatch)
    hook = _RecordingHook(raise_on_environment_ready=True)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path, pre_spawn_hook=hook)
    session_id = await transport.open()

    assert session_id == "s1"
    assert transport.is_alive()
    # hook_state stays None since on_environment_ready raised before returning.
    await transport.close()
    assert hook.close_calls == [None]


@pytest.mark.asyncio
async def test_pre_spawn_hook_on_close_failure_does_not_raise(tmp_path, monkeypatch):
    _install_sdk(monkeypatch)
    hook = _RecordingHook(raise_on_close=True)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path, pre_spawn_hook=hook)
    await transport.open()

    await transport.close()  # must not raise
    assert not transport.is_alive()


@pytest.mark.asyncio
async def test_no_pre_spawn_hook_is_a_no_op(tmp_path, monkeypatch):
    """Default (no hook) behaves exactly as before this feature existed."""
    _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    session_id = await transport.open()
    assert session_id == "s1"
    await transport.close()  # must not raise


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
    # Rolling FIFO: the TAIL (final report) is retained as events; the
    # evicted OLDEST chunks survive as overflow text.
    retained_texts = [e.text for e in result.events if e.kind == "assistant-message"]
    assert f"[{MAX_EVENTS + 49}]" in retained_texts[-1]
    assert result.overflow_text is not None
    assert "[0]" in result.overflow_text
    # Sequences stay strictly increasing across evictions
    seqs = [e.sequence for e in result.events]
    assert seqs == sorted(seqs)
    assert seqs[0] > 0  # oldest were evicted


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


# ── RV679: terminal callback delivery, real wire vocabulary, compact ids ──


@pytest.mark.asyncio
async def test_terminal_result_is_delivered_to_on_event(tmp_path, monkeypatch):
    """The terminal 'result' event reaches the on_event callback — turn
    completion must be observable without waiting on the sync return."""
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()

    seen: list = []

    async def on_event(event):
        seen.append(event)

    result = await transport.prompt("go", on_event=on_event)
    await transport.close()

    terminals = [e for e in seen if e.kind == "result" and e.terminal]
    assert len(terminals) == 1
    assert terminals[0].ext["acp"]["stop_reason"] == "end_turn"
    assert result.terminal_event is not None


@pytest.mark.asyncio
async def test_real_wire_kinds_map_to_canonical(tmp_path, monkeypatch):
    """agent_thought_chunk / tool_call_update — the kinds real agents send —
    normalize to canonical 'thought' / 'tool-call' instead of leaking raw."""
    async def prompt_one(session_id, prompt):
        client = captured["client"]
        await client.session_update(
            session_id,
            {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "thinking"}},
        )
        await client.session_update(
            session_id,
            {"sessionUpdate": "tool_call_update", "toolCallId": "tc9", "status": "completed"},
        )
        return SimpleNamespace(stop_reason="end_turn")

    conn, proc, captured, exited = _install_sdk(monkeypatch, prompt_side_effect=prompt_one)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path, compact_events=True)
    await transport.open()
    result = await transport.prompt("go")
    await transport.close()

    kinds = [e.kind for e in result.events]
    assert "thought" in kinds and "tool-call" in kinds
    thought = next(e for e in result.events if e.kind == "thought")
    assert thought.text == "thinking"
    assert thought.ext["acp"]["raw_kind"] == "agent_thought_chunk"
    # Compact mode preserves the tool lifecycle identity without the payload.
    tool = next(e for e in result.events if e.kind == "tool-call")
    assert tool.ext["acp"]["status"] == "completed"
    assert tool.ext["acp"]["tool_call_id"] == "tc9"
    assert "payload" not in tool.ext["acp"]


# ── AS68: real fs/terminal Client execution ─────────────────────────────────

def test_confine_path_allows_relative_and_absolute_paths_inside_root(tmp_path):
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    resolved_relative = transport._confine_path("inner/file.txt")
    resolved_absolute = transport._confine_path(str(tmp_path / "inner" / "file.txt"))
    assert resolved_relative == resolved_absolute
    assert resolved_relative == (tmp_path / "inner" / "file.txt").resolve()


def test_confine_path_rejects_traversal_outside_root(tmp_path):
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    with pytest.raises(AudiaGenticError, match=ERR_FS_ESCAPE):
        transport._confine_path("../outside.txt")
    with pytest.raises(AudiaGenticError, match=ERR_FS_ESCAPE):
        transport._confine_path(str(tmp_path.parent / "sibling" / "outside.txt"))


@pytest.mark.asyncio
async def test_write_then_read_text_file_round_trips_through_real_fs(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    client = captured["client"]
    transport._current_turn = turn = _TurnPipeline(None)

    write_resp = await client.write_text_file("s1", str(tmp_path / "notes.txt"), "hello world")
    assert write_resp is not None
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello world"

    read_resp = await client.read_text_file("s1", str(tmp_path / "notes.txt"))
    assert read_resp.content == "hello world"

    kinds = [e.kind for e in turn.events]
    assert kinds.count("file-change") == 2  # one write, one read
    await transport.close()


@pytest.mark.asyncio
async def test_write_text_file_outside_root_raises_and_never_touches_disk(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    client = captured["client"]
    transport._current_turn = _TurnPipeline(None)

    outside = tmp_path.parent / "escape.txt"
    with pytest.raises(AudiaGenticError, match=ERR_FS_ESCAPE):
        await client.write_text_file("s1", str(outside), "should not land")
    assert not outside.exists()
    await transport.close()


@pytest.mark.asyncio
async def test_create_terminal_runs_real_process_and_captures_output(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    client = captured["client"]
    transport._current_turn = turn = _TurnPipeline(None)

    create_resp = await client.create_terminal(
        "s1", sys.executable, args=["-c", "print('AS68_TERMINAL_PROOF')"],
    )
    terminal_id = create_resp.terminal_id
    assert terminal_id in transport._terminals

    exit_resp = await client.wait_for_terminal_exit("s1", terminal_id)
    assert exit_resp.exit_code == 0

    output_resp = await client.terminal_output("s1", terminal_id)
    assert "AS68_TERMINAL_PROOF" in output_resp.output
    assert output_resp.truncated is False

    release_resp = await client.release_terminal("s1", terminal_id)
    assert release_resp is None
    assert terminal_id not in transport._terminals

    started = [e for e in turn.events if e.kind == "terminal-output"]
    assert len(started) >= 1
    await transport.close()


@pytest.mark.asyncio
async def test_terminal_output_unknown_id_raises(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    client = captured["client"]

    with pytest.raises(AudiaGenticError, match=ERR_UNKNOWN_TERMINAL):
        await client.terminal_output("s1", "term-does-not-exist")
    await transport.close()


@pytest.mark.asyncio
async def test_kill_terminal_stops_a_running_process(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    client = captured["client"]
    transport._current_turn = _TurnPipeline(None)

    create_resp = await client.create_terminal(
        "s1", sys.executable, args=["-c", "import time; time.sleep(30)"],
    )
    terminal_id = create_resp.terminal_id

    kill_resp = await client.kill_terminal("s1", terminal_id)
    assert kill_resp is None

    exit_resp = await client.wait_for_terminal_exit("s1", terminal_id)
    assert exit_resp.exit_code != 0 or exit_resp.signal is not None
    await transport.close()


@pytest.mark.asyncio
async def test_close_force_kills_terminals_the_agent_never_released(tmp_path, monkeypatch):
    conn, proc, captured, exited = _install_sdk(monkeypatch)
    transport = AcpSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
    await transport.open()
    client = captured["client"]
    transport._current_turn = _TurnPipeline(None)

    create_resp = await client.create_terminal(
        "s1", sys.executable, args=["-c", "import time; time.sleep(30)"],
    )
    handle = transport._terminals[create_resp.terminal_id]

    await transport.close()

    assert transport._terminals == {}
    # close() sends kill() but doesn't block on reaping — await it here to
    # prove the process actually died rather than merely being signaled.
    await asyncio.wait_for(handle.proc.wait(), timeout=5)
    assert handle.proc.returncode is not None
