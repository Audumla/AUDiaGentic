"""Recovery ownership and retry tests; never touch the user's browser."""

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime import (
    GptAutoProviderRuntime,
    ProviderState,
)

from .test_chat_unresolved_reconciliation import _chat
from .test_greenfield_config_urls import valid_config


def recovery_runtime():
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    calls = []

    async def stop():
        calls.append("stop")

    def replaced():
        calls.append("invalidate")

    async def reconcile(pages):
        calls.append("reconcile")
        chat.state = "busy"

    chat = SimpleNamespace(active_turn_id="turn", state="busy",
                           bridge_replaced=replaced, reconcile=reconcile)
    runtime._bridge = SimpleNamespace(stop=stop)
    runtime.state = ProviderState.AVAILABLE
    runtime._chats = {"owned": chat}
    return runtime, chat, calls


@pytest.mark.asyncio
async def test_outage_retries_attempts_and_coalesces_waiters(monkeypatch):
    runtime, chat, calls = recovery_runtime()
    attempts = 0

    async def list_pages(method):
        assert method == "list_pages"
        return []

    async def available():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("browser offline")
        runtime._bridge = SimpleNamespace(call=list_pages)
        runtime.state = ProviderState.AVAILABLE

    monkeypatch.setattr(runtime, "ensure_available", available)
    await asyncio.wait_for(asyncio.gather(runtime.recover(), runtime.recover()), 3)
    assert attempts == 3
    assert calls == ["invalidate", "stop", "reconcile"]
    assert chat.active_turn_id == "turn"


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_recovery(monkeypatch):
    runtime, _, calls = recovery_runtime()
    entered, release = asyncio.Event(), asyncio.Event()

    async def pages(method):
        return []

    async def available():
        entered.set()
        await release.wait()
        runtime._bridge = SimpleNamespace(call=pages)
        runtime.state = ProviderState.AVAILABLE

    monkeypatch.setattr(runtime, "ensure_available", available)
    waiter = asyncio.create_task(runtime.recover())
    await asyncio.wait_for(entered.wait(), 1)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not runtime._recovery_task.done()
    release.set()
    await asyncio.wait_for(runtime._recovery_task, 1)
    assert calls.count("reconcile") == 1


@pytest.mark.asyncio
async def test_expired_request_owner_stops_retry_without_provider_actions(monkeypatch):
    runtime, chat, calls = recovery_runtime()
    chat._page_mutation_owner_is_live = lambda: False

    async def forbidden():
        raise AssertionError("expired request must not reconnect")

    monkeypatch.setattr(runtime, "ensure_available", forbidden)
    await asyncio.wait_for(runtime.recover(), 1)
    assert calls == ["invalidate", "stop"]


@pytest.mark.asyncio
async def test_rebind_failure_is_isolated_and_retried(monkeypatch):
    runtime, chat, calls = recovery_runtime()
    attempts = 0

    async def reconcile(pages):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("renderer vanished")
        chat.state = "busy"

    chat.reconcile = reconcile

    async def pages(method):
        return []

    async def available():
        runtime._bridge = SimpleNamespace(call=pages)
        runtime.state = ProviderState.AVAILABLE

    monkeypatch.setattr(runtime, "ensure_available", available)
    await asyncio.wait_for(runtime.recover(), 2)
    assert attempts == 2
    assert calls.count("stop") == 1


@pytest.mark.asyncio
async def test_replacement_page_requires_original_project_before_binding():
    chat = _chat()
    chat.chat_url = "https://chatgpt.com/g/g-p-original/c/conversation"
    original_handle = chat.page_handle
    assert not await chat._adopt_recovery_page({
        "pageHandle": "foreign", "targetId": "replacement",
        "url": "https://chatgpt.com/g/g-p-other/c/conversation",
    })
    assert chat.page_handle == original_handle


@pytest.mark.asyncio
async def test_closed_chat_is_not_moved_back_to_recovery():
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState

    chat = _chat()
    chat.state = ChatState.CLOSED
    chat.bridge_replaced()
    assert chat.state is ChatState.CLOSED


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["completed", "generating", "wrong-prompt", "owner-expired"])
async def test_replacement_target_reproves_owned_turn_without_send(case):
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
    from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

    chat = _chat()
    chat.state = ChatState.RECOVERING
    chat.active_turn_id = "owned-turn"
    chat.provider_session_id = "conversation"
    chat.chat_url = "https://chatgpt.com/g/g-p-original/c/conversation"
    updates = []
    chat.binding_sink = updates.append
    chat.runtime = SimpleNamespace()

    async def snapshot(**kwargs):
        if case == "owner-expired":
            chat.set_page_mutation_owner_probe(lambda: False)
        return ChatSnapshot(
            url=chat.chat_url, latest_user_id="foreign" if case == "wrong-prompt" else "u1",
            user_message_ids=("u1",), generating=case == "generating",
            composer_present=True, composer_editable=True, user_count=1, assistant_count=1,
            latest_assistant_id="a1", latest_user_text="owned", latest_assistant_text="answer",
            dom_signals=frozenset(), error_present=False,
        )

    chat.snapshot = snapshot
    adopted = await chat._adopt_recovery_page({
        "pageHandle": "replacement", "targetId": "new-target", "url": chat.chat_url,
    })
    assert adopted is (case in {"completed", "generating"})
    assert len(updates) == int(adopted)
    assert chat.state is (ChatState.BUSY if adopted else ChatState.RECOVERING)
    assert chat._replacement_target_pending is not adopted
