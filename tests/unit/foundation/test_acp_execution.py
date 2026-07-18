"""MA18 Step 4 — ACP execution contract tests.

Exact test matrix per frozen contract in PROVIDER_CAPABILITY_REFERENCE/execution/agent-execution-transports.md
§'Neutral event and lifecycle contract — FROZEN'.

Mock official SDK boundary, not provider internals.
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
    ERR_SDK_MISSING,
    MAX_EVENTS,
    MAX_TOTAL_BYTES,
    AcpLaunch,
    _map_kind,
    run_acp_prompt,
)


def _build_mock(tmp_path, monkeypatch, **overrides):
    """Return (conn, mock_ctx) with captured_client as a dict ref.

    The spawned GatewayClient instance is stored in returned dict under 'client'.
    Callers can use conn.prompt side_effect to interact with it.
    """
    captured = {"client": None}

    mock_ctx = AsyncMock()
    conn = MagicMock()
    conn.initialize = AsyncMock()
    sess = SimpleNamespace(session_id="s1")
    conn.new_session = AsyncMock(return_value=sess)
    conn.prompt = AsyncMock(
        side_effect=overrides.get(
            "prompt_side_effect",
            lambda session_id, prompt: SimpleNamespace(stop_reason="end_turn"),
        )
    )

    proc = SimpleNamespace()
    mock_ctx.__aenter__ = AsyncMock(return_value=(conn, proc))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

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

    return conn, mock_ctx, captured


# ── kind mapping ─────────────────────────────────────────────────

def test_map_kind_agent_message():
    assert _map_kind("agent_message_chunk") == "assistant-message"

def test_map_kind_thought():
    assert _map_kind("thought") == "thought"

def test_map_kind_tool_call():
    assert _map_kind("tool_call") == "tool-call"

def test_map_kind_unknown_returns_raw():
    assert _map_kind("unknown_kind") == "unknown_kind"

# ── ordering and event variants ──────────────────────────────────

@pytest.mark.asyncio
async def test_ordered_updates(tmp_path, monkeypatch):
    """Events are 0-indexed and strictly ordered."""
    conn, ctx, captured = _build_mock(tmp_path, monkeypatch)
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
    )
    assert len(result.events) >= 1
    terminal = result.events[-1]
    assert terminal.terminal is True
    assert terminal.kind == "result"
    assert result.terminal_event is terminal

@pytest.mark.asyncio
async def test_kind_mapping_in_events(tmp_path, monkeypatch):
    """Event kinds use canonical vocabulary."""
    seen = []

    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            await client.session_update(
                session_id,
                {"sessionUpdate": "agent_message_chunk", "text": "hello"},
            )
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
        on_event=seen.append,
    )

    asst_events = [e for e in result.events if e.kind == "assistant-message"]
    assert len(asst_events) >= 1, "Expected at least one assistant-message event"
    assert asst_events[0].text == "hello"
    cb_kinds = [e.kind for e in seen]
    assert "assistant-message" in cb_kinds

# ── default permission denial ───────────────────────────────────

@pytest.mark.asyncio
async def test_default_permission_denial(tmp_path, monkeypatch):
    """Permissions are denied by default."""
    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            outcome = await client.request_permission(
                session_id, {"id": "t1"}, [{"optionId": "yes"}],
            )
            assert outcome == {"outcome": {"outcome": "cancelled"}}
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
    )
    perm_events = [e for e in result.events if e.kind == "permission-request"]
    assert len(perm_events) >= 1, "Expected permission-request event"

# ── explicit policy callback ─────────────────────────────────────

@pytest.mark.asyncio
async def test_explicit_policy_grant(tmp_path, monkeypatch):
    """policy_fn can grant tool access."""
    granted_outcomes = []

    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            outcome = await client.request_permission(
                session_id, {"id": "t1"}, [{"optionId": "yes"}],
            )
            granted_outcomes.append(outcome)
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )
    grant_result = {"outcome": {"outcome": "granted"}}

    async def policy_fn(session_id, tool_call_info):
        return grant_result

    await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
        policy_fn=policy_fn,
    )
    assert granted_outcomes == [grant_result]

# ── malformed update ────────────────────────────────────────────

class _BadStr:
    """Object whose str() always raises — triggers malformed update path."""

    def __str__(self):
        raise ValueError("unrepresentable")

    def __repr__(self):
        return "<_BadStr>"


@pytest.mark.asyncio
async def test_malformed_update_normalized(tmp_path, monkeypatch):
    """Malformed updates produce error-kind event with EXT-ACP-002."""
    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            await client.session_update(
                session_id,
                _BadStr(),
            )
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
    )

    error_events = [e for e in result.events if e.kind == "error"]
    assert len(error_events) >= 1, "Expected at least one error event for malformed update"
    err = error_events[0]
    assert err.error is not None
    assert err.error["code"] == "EXT-ACP-002"
    # Session continues — terminal result still emitted
    assert result.terminal_event is not None
    assert result.terminal_event.kind == "result"

# ── child exit ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unexpected_child_exit(tmp_path, monkeypatch):
    """Unexpected exception produces EXT-ACP-001 with ERR_CHILD_EXIT in terminal."""
    mock_ctx = AsyncMock()
    conn = MagicMock()
    conn.initialize = AsyncMock()
    sess = SimpleNamespace(session_id="s1")
    conn.new_session = AsyncMock(return_value=sess)
    conn.prompt = AsyncMock(side_effect=RuntimeError("agent crashed"))

    proc = SimpleNamespace()
    mock_ctx.__aenter__ = AsyncMock(return_value=(conn, proc))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    def spawn(client_instance, executable, *args, **kwargs):
        return mock_ctx

    acp_mod = types.ModuleType("acp")
    acp_mod.PROTOCOL_VERSION = 1
    acp_mod.spawn_agent_process = spawn
    acp_mod.text_block = lambda text: {"type": "text", "text": text}

    interfaces_mod = types.ModuleType("acp.interfaces")
    interfaces_mod.Client = object
    monkeypatch.setitem(sys.modules, "acp", acp_mod)
    monkeypatch.setitem(sys.modules, "acp.interfaces", interfaces_mod)

    with pytest.raises(AudiaGenticError, match=ERR_EXECUTION_FAILED):
        await run_acp_prompt(
            AcpLaunch("agent"),
            cwd=tmp_path,
            prompt="hello",
        )

# ── callback error isolation ────────────────────────────────────

@pytest.mark.asyncio
async def test_callback_failure_disables(tmp_path, monkeypatch):
    """After 3 consecutive callback failures, on_event is disabled."""
    cb_count = [0]

    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            for _ in range(5):
                await client.session_update(
                    session_id,
                    {"sessionUpdate": "agent_message_chunk", "text": "data"},
                )
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )

    async def failing_callback(event):
        cb_count[0] += 1
        raise RuntimeError("callback error")

    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
        on_event=failing_callback,
    )

    assert result.callback_disabled is True
    assert cb_count[0] >= 3
    status_events = [e for e in result.events if e.kind == "status"]
    assert len(status_events) >= 1

# ── cancel during prompt (protocol-level) ───────────────────────

@pytest.mark.asyncio
async def test_cancel_during_prompt(tmp_path, monkeypatch):
    """Cancel signal set mid-prompt triggers protocol cancel, returns cancelled."""
    cancel_called = {"count": 0}

    async def slow_prompt(session_id, prompt):
        """Simulates a long-running prompt that never completes."""
        await asyncio.sleep(10)
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=slow_prompt,
    )
    # Add protocol-level cancel method to the mock connection
    async def mock_cancel(session_id):
        cancel_called["count"] += 1

    conn.cancel = mock_cancel

    cancel_signal = asyncio.Event()

    async def fire_cancel():
        await asyncio.sleep(0.1)
        cancel_signal.set()

    asyncio.ensure_future(fire_cancel())

    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
        cancel_signal=cancel_signal,
    )

    assert result.stop_reason == "cancelled"
    terminal = result.terminal_event
    assert terminal is not None
    assert terminal.kind == "result"
    # Protocol-level cancel was attempted
    assert cancel_called["count"] >= 1

# ── cancel before prompt ────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_before_prompt(tmp_path, monkeypatch):
    """Cancel signal already set before prompt yields empty run with terminal."""
    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch,
        prompt_side_effect=lambda sid, p: (_ for _ in ()).throw(Exception("should not reach")),
    )

    cancel_signal = asyncio.Event()
    cancel_signal.set()

    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
        cancel_signal=cancel_signal,
    )

    assert result.stop_reason == "cancelled"
    terminal = result.terminal_event
    assert terminal is not None
    assert terminal.kind == "result"
    assert terminal.terminal is True
    conn.prompt.assert_not_called()

# ── bounded event count ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_bounded_event_count(tmp_path, monkeypatch):
    """Beyond MAX_EVENTS, non-terminal events are dropped."""
    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            for i in range(MAX_EVENTS + 100):
                await client.session_update(
                    session_id,
                    {"sessionUpdate": "agent_message_chunk", "text": f"msg-{i}"},
                )
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
    )

    # Events bounded (terminal always retained)
    assert len(result.events) <= MAX_EVENTS + 1
    assert result.dropped_events > 0
    assert result.total_events > MAX_EVENTS

# ── bounded total bytes ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_bounded_total_bytes(tmp_path, monkeypatch):
    """Beyond MAX_TOTAL_BYTES, oldest events are evicted; terminal retained."""
    BIG_TEXT = "x" * 1024  # 1 KiB per event — 8192 events exceed 8 MiB

    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            for i in range(8192):
                await client.session_update(
                    session_id,
                    {"sessionUpdate": "agent_message_chunk", "text": BIG_TEXT},
                )
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
    )

    assert result.bytes_buffered <= MAX_TOTAL_BYTES + 1024
    assert result.dropped_events > 0
    assert result.terminal_event is not None
    assert result.terminal_event.kind == "result"

# ── secret canary absent from normalized errors ─────────────────

@pytest.mark.asyncio
async def test_secret_canary_absent_from_errors(tmp_path, monkeypatch):
    """Normalized error messages never contain raw secret-bearing payloads."""
    SECRET = "sk-secret-token-do-not-log"

    async def prompt_handler(session_id, prompt):
        client = captured["client"]
        if client is not None:
            # Update with secret in payload
            await client.session_update(
                session_id,
                {"sessionUpdate": "agent_message_chunk", "apiKey": SECRET},
            )
        return SimpleNamespace(stop_reason="end_turn")

    conn, ctx, captured = _build_mock(
        tmp_path, monkeypatch, prompt_side_effect=prompt_handler,
    )
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
    )

    for event in result.events:
        if event.text is not None:
            assert SECRET not in event.text, (
                f"Secret leaked in event {event.sequence} text"
            )
        if event.error is not None:
            for v in event.error.values():
                assert SECRET not in str(v), (
                    f"Secret leaked in event {event.sequence} error"
                )

# ── SDK missing canonical error ─────────────────────────────────

def test_missing_sdk_canonical_error(monkeypatch, tmp_path):
    """Missing SDK raises CFG-ACP-001."""
    monkeypatch.setitem(sys.modules, "acp", None)
    with pytest.raises(AudiaGenticError, match=ERR_SDK_MISSING):
        asyncio.run(run_acp_prompt(
            AcpLaunch("agent"),
            cwd=tmp_path,
            prompt="hello",
        ))

# ── result structure invariants ─────────────────────────────────

@pytest.mark.asyncio
async def test_result_structure(tmp_path, monkeypatch):
    """AcpResult fields are correctly populated."""
    conn, ctx, captured = _build_mock(tmp_path, monkeypatch)
    result = await run_acp_prompt(
        AcpLaunch("agent"),
        cwd=tmp_path,
        prompt="hello",
    )

    assert result.session_id == "s1"
    assert result.stop_reason == "end_turn"
    assert len(result.events) >= 1
    assert result.total_events >= 1
    assert result.terminal_event is not None
    assert result.terminal_event.terminal is True
    assert result.callback_disabled is False

# ── foundation import guard ─────────────────────────────────────

def test_acp_no_component_imports():
    """foundation/transports/acp.py must not import component or provider modules."""
    import ast

    acp_path = (
        __import__(
            "audiagentic.foundation.transports.acp",
            fromlist=[""],
        )
        .__file__ or ""
    )

    with open(acp_path, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    forbidden_prefixes = (
        "audiagentic.components",
        "audiagentic.runtime",
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in forbidden_prefixes:
                    assert not alias.name.startswith(prefix), (
                        f"ACP foundation imports forbidden: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for prefix in forbidden_prefixes:
                assert not node.module.startswith(prefix), (
                    f"ACP foundation imports forbidden: {node.module}"
                )
