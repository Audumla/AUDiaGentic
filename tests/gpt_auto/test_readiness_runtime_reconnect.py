"""Lazy readiness reconnects transport without replaying provider work."""

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
from audiagentic.components.providers.adapters.gpt_auto.runtime import (
    GptAutoProviderRuntime,
    ProviderState,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_chat_unresolved_reconciliation import _chat


@pytest.mark.asyncio
@pytest.mark.parametrize("submitted", [False, True])
async def test_live_chat_readiness_reconnects_failed_idle_runtime(monkeypatch, submitted):
    chat = _chat(unresolved=submitted)
    runtime = GptAutoProviderRuntime(chat.config)
    chat.runtime = runtime
    chat.state = ChatState.RECOVERING
    chat.provider_session_id = "conversation"
    chat.chat_url = "https://chatgpt.com/g/g-p-original/c/conversation"
    chat.page_handle = None
    runtime._chats = {chat.ag_session_id: chat}
    runtime.state = ProviderState.FAILED
    calls = []

    async def available():
        calls.append("probe")
        return True

    async def call(method, params=None, **kwargs):
        assert method == "list_pages", "Reconnect must not navigate or submit"
        calls.append(method)
        return []

    bridge = SimpleNamespace(call=call)

    async def connect():
        calls.append("connect")
        return bridge

    async def no_background_work(_bridge):
        return None

    async def validate():
        assert runtime.bridge is bridge
        assert runtime.state is ProviderState.AVAILABLE
        calls.append("validate")

    async def find(*args, **kwargs):
        return None

    monkeypatch.setattr(runtime, "_cdp_available", available)
    monkeypatch.setattr(runtime, "_connect_bridge", connect)
    monkeypatch.setattr(runtime, "_route_events", no_background_work)
    monkeypatch.setattr(runtime, "_reap_idle_tabs", no_background_work)
    monkeypatch.setattr(runtime, "find_conversation_page", find)
    monkeypatch.setattr(chat, "_validate_page_binding", validate)
    if not submitted:
        # Test connection ordering separately from existing idle-page recovery.
        async def reconcile(pages):
            assert runtime.bridge is bridge
            chat.page_handle = "reattached"
            chat._move(ChatState.READY)

        monkeypatch.setattr(chat, "reconcile", reconcile)
        await chat.ensure_ready()
        assert chat.state is ChatState.READY
    else:
        chat.set_page_mutation_owner_probe(lambda: True)
        checkpoint = chat._private_terminal_checkpoint_projection()
        with pytest.raises(AudiaGenticError, match="EXT-GPTAUTO-004"):
            await chat.ensure_ready()
        assert chat.state is ChatState.RECOVERING
        assert chat.unresolved_turn_pending
        assert chat._private_terminal_checkpoint_projection() == checkpoint
    assert calls[:3] == ["probe", "connect", "validate"]
    await asyncio.gather(runtime._event_task, runtime._tab_reaper_task)


@pytest.mark.asyncio
async def test_readiness_retries_runtime_connection_before_using_bridge(monkeypatch):
    chat = _chat(unresolved=False)
    chat.state = ChatState.READY
    attempts = 0
    validated = []

    async def connect():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("remote endpoint still offline")

    async def validate():
        validated.append(True)

    chat.runtime = SimpleNamespace(ensure_available=connect)
    monkeypatch.setattr(chat, "_validate_page_binding", validate)
    with pytest.raises(ConnectionError):
        await chat.ensure_ready()
    assert not validated
    await chat.ensure_ready()
    assert attempts == 2
    assert validated == [True]
