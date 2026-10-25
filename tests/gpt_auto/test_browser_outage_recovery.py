"""Recovery ownership and retry tests; never touch the user's browser."""

import asyncio
import json
import threading
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
    assert chat._replacement_target_pending is False
    assert chat.page_handle == ("replacement" if adopted else "page-1")


@pytest.mark.asyncio
async def test_real_socket_outage_rebinds_new_target_and_reads_completed_reply(monkeypatch, tmp_path):
    """Real disposable sockets + runtime + chat; no live user browser is stopped."""
    from websockets.asyncio.server import serve

    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.queue.queue import GatewayQueueManager
    from audiagentic.components.providers.adapters.gpt_auto.cdp.client import CdpClient
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
    from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

    runtime, _, _ = recovery_runtime()
    manager = GatewayQueueManager()
    released, worker_started = threading.Event(), threading.Event()
    worker_order = []
    first = store.build_record(execution_profile_id="outage", prompt_body="owned")
    second = store.build_record(execution_profile_id="outage", prompt_body="follower")
    for record in (first, second):
        store.write_record(tmp_path, record)

    def runner(project, record):
        worker_order.append(record["request-id"])
        if record["request-id"] == first["request-id"]:
            worker_started.set()
            if not released.wait(8):
                raise AssertionError("recovery never released active request")
        return store.transition_record(project, record["request-id"], "completed", updates={
            "output": observed[-1] if record["request-id"] == first["request-id"] else "follower completed",
        })

    manager.enqueue(tmp_path, first, {"virtual-capacity": 1}, runner)
    assert await asyncio.to_thread(worker_started.wait, 2)
    manager.enqueue(tmp_path, second, {"virtual-capacity": 1}, runner)
    chat = _chat()
    chat.runtime = runtime
    chat.state = ChatState.BUSY
    chat.active_turn_id = "owned-turn"
    chat.provider_session_id = "conversation"
    chat.chat_url = "https://chatgpt.com/g/g-p-original/c/conversation"
    chat.target_id = "old-target"
    runtime._chats = {chat.ag_session_id: chat}
    methods = []
    endpoint = None
    attempts = 0

    async def handler(socket):
        async for raw in socket:
            request = json.loads(raw)
            methods.append(request["method"])
            if request["method"] == "Target.getTargets":
                result = {"targetInfos": [{"pageHandle": "new-handle", "targetId": "new-target", "url": chat.chat_url}]}
            elif request["method"] == "Runtime.evaluate":
                result = {"result": {"value": "completed while disconnected"}}
            else:
                raise AssertionError(f"unexpected provider side effect: {request['method']}")
            await socket.send(json.dumps({"id": request["id"], "result": result}))

    client = None

    class Bridge:
        async def call(self, method):
            assert method == "list_pages"
            return (await client.command("Target.getTargets"))["targetInfos"]

        async def stop(self):
            await client.stop()

    async def available():
        nonlocal attempts, client
        attempts += 1
        if endpoint is None:
            raise ConnectionError("endpoint absent beyond first connect attempt")
        client = CdpClient(endpoint, default_timeout=1)
        await client.start()
        runtime._bridge = Bridge()
        runtime.state = ProviderState.AVAILABLE

    async def find_page(*args, **kwargs):
        return (await runtime.bridge.call("list_pages"))[0]

    observed = []

    async def snapshot(**kwargs):
        reply = await client.command("Runtime.evaluate", {"expression": "read-only snapshot"})
        observed.append(reply["result"]["value"])
        return ChatSnapshot(
            url=chat.chat_url, composer_present=True, composer_editable=True,
            user_count=1, assistant_count=1, latest_user_id="u1", user_message_ids=("u1",),
            latest_assistant_id="a1", latest_user_text="owned", latest_assistant_text=observed[-1],
            generating=False, dom_signals=frozenset({"completion-control"}), error_present=False,
        )

    monkeypatch.setattr(runtime, "ensure_available", available)
    monkeypatch.setattr(runtime, "find_conversation_page", find_page)
    monkeypatch.setattr(chat, "snapshot", snapshot)
    # Adoption is the path under test; avoid unrelated title/materialization work.
    async def reconcile(pages):
        await chat._adopt_recovery_page(pages[0])
    monkeypatch.setattr(chat, "reconcile", reconcile)
    pending = asyncio.create_task(runtime.recover())
    try:
        await asyncio.sleep(0.35)
        assert attempts >= 2
        assert store.read_record(tmp_path, first["request-id"])["state"] == "running"
        assert store.read_record(tmp_path, second["request-id"])["state"] == "queued"
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            endpoint = f"ws://127.0.0.1:{port}/new-browser-generation"
            await asyncio.wait_for(pending, 3)
            assert chat.target_id == "new-target"
            assert chat.state is ChatState.BUSY
            assert observed == ["completed while disconnected"]
            assert methods == ["Target.getTargets", "Runtime.evaluate"]
            released.set()
            terminal = await asyncio.to_thread(manager.wait, tmp_path, first["request-id"], timeout_seconds=3)
            follower = await asyncio.to_thread(manager.wait, tmp_path, second["request-id"], timeout_seconds=3)
            assert terminal["state"] == follower["state"] == "completed"
            assert terminal["output"] == observed[-1]
            assert worker_order == [first["request-id"], second["request-id"]]
    finally:
        released.set()
        manager.shutdown()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        if client is not None:
            await client.stop()


@pytest.mark.asyncio
async def test_concurrent_reopen_creates_one_background_conversation(monkeypatch):
    runtime, _, _ = recovery_runtime()
    url = "https://chatgpt.com/g/g-p-original/c/conversation"
    pages, actions = [], []

    async def find_page(*args, **kwargs):
        await asyncio.sleep(0)
        return pages[0] if pages else None

    async def create(**kwargs):
        assert kwargs == {"background_only": True}
        actions.append("create")
        return "new-handle"

    async def call(method, params=None):
        actions.append(method)
        if method == "navigate":
            pages.append({"pageHandle": "new-handle", "targetId": "new-target", "url": params["url"]})
        elif method == "list_pages":
            return pages
        else:
            raise AssertionError(f"unexpected action: {method}")

    runtime._bridge = SimpleNamespace(call=call)
    monkeypatch.setattr(runtime, "find_conversation_page", find_page)
    monkeypatch.setattr(runtime, "create_chat_page", create)
    first, second = await asyncio.gather(
        runtime.reopen_conversation_page(url), runtime.reopen_conversation_page(url),
    )
    assert first == second
    assert actions == ["create", "navigate", "list_pages"]


@pytest.mark.asyncio
async def test_expired_reopen_owner_is_not_shared_task_cancellation():
    runtime, _, _ = recovery_runtime()
    with pytest.raises(RuntimeError, match="owner expired"):
        await runtime.reopen_conversation_page(
            "https://chatgpt.com/g/g-p-original/c/conversation", owner_is_live=lambda: False,
        )


@pytest.mark.asyncio
async def test_expired_session_does_not_starve_another_active_session(monkeypatch):
    runtime, chat, calls = recovery_runtime()
    expired = SimpleNamespace(active_turn_id="expired", state="busy", bridge_replaced=lambda: None)
    live = True
    expired._page_mutation_owner_is_live = lambda: live

    async def expire(pages):
        nonlocal live
        live = False
        raise RuntimeError("conversation recovery owner expired")

    expired.reconcile = expire
    runtime._chats = {"expired": expired, "owned": chat}

    async def pages(method):
        return []

    async def available():
        runtime._bridge = SimpleNamespace(call=pages)
        runtime.state = ProviderState.AVAILABLE

    monkeypatch.setattr(runtime, "ensure_available", available)
    await asyncio.wait_for(runtime.recover(), 1)
    assert calls.count("reconcile") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["snapshot", "binding-sink"])
async def test_rejected_adoption_releases_claim_and_restores_binding(failure):
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
    from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

    runtime, _, _ = recovery_runtime()
    chat = _chat()
    chat.runtime = runtime
    chat.state = ChatState.RECOVERING
    chat.active_turn_id = "owned"
    chat.provider_session_id = "conversation"
    chat.chat_url = "https://chatgpt.com/g/g-p-original/c/conversation"
    previous = (chat.page_handle, chat.target_id, chat._page_generation)

    async def snapshot(**kwargs):
        if failure == "snapshot":
            raise ConnectionError("renderer gone")
        return ChatSnapshot(url=chat.chat_url, composer_present=True, composer_editable=True,
            user_count=1, assistant_count=1, latest_user_id="u1", user_message_ids=("u1",),
            latest_assistant_id="a1", latest_user_text="owned", latest_assistant_text="answer",
            generating=False, dom_signals=frozenset(), error_present=False)

    def reject(update):
        raise RuntimeError("checkpoint owner changed")

    chat.snapshot, chat.binding_sink = snapshot, reject
    with pytest.raises((RuntimeError, ConnectionError)):
        await chat._adopt_recovery_page({"pageHandle": "speculative", "targetId": "new", "url": chat.chat_url})
    assert "speculative" not in runtime._page_owners
    assert (chat.page_handle, chat.target_id, chat._page_generation) == previous


@pytest.mark.asyncio
async def test_gateway_restart_open_joins_outage_coordinator_without_send(monkeypatch):
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
    from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    chat = _chat()
    chat.runtime = runtime
    chat.page_handle = None
    chat.provider_session_id = "conversation"
    chat.chat_url = "https://chatgpt.com/g/g-p-original/c/conversation"
    chat.defer_unresolved_reconciliation()
    attempts = 0
    page = {"pageHandle": "restored", "targetId": "new-target", "url": chat.chat_url}

    async def pages(method):
        assert method == "list_pages"
        return [page]

    async def available():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            runtime.state = ProviderState.FAILED
            raise ConnectionError("browser offline during gateway restart")
        runtime.state = ProviderState.AVAILABLE
        runtime._bridge = SimpleNamespace(call=pages)

    async def find(*args, **kwargs):
        return page

    async def snapshot(**kwargs):
        return ChatSnapshot(url=chat.chat_url, composer_present=True, composer_editable=True,
            user_count=1, assistant_count=1, latest_user_id="u1", user_message_ids=("u1",),
            latest_assistant_id="a1", latest_user_text="owned", latest_assistant_text="answer",
            generating=True, dom_signals=frozenset(), error_present=False)

    monkeypatch.setattr(runtime, "ensure_available", available)
    monkeypatch.setattr(runtime, "find_conversation_page", find)
    chat.snapshot = snapshot
    await asyncio.wait_for(chat.open(), 2)
    assert attempts == 3
    assert chat.state is ChatState.READY
    assert chat.unresolved_turn_pending
    assert chat.target_id == "new-target"


@pytest.mark.asyncio
async def test_page_closed_before_socket_loss_retains_recovering_chat():
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState

    chat = _chat()
    chat.state = ChatState.BUSY
    chat.active_turn_id = "owned"

    async def disconnected(*args, **kwargs):
        raise ConnectionError("socket just disappeared")

    chat.runtime = SimpleNamespace(release_page=lambda *args: None, bridge=SimpleNamespace(call=disconnected))
    await chat.page_lost("page-1")
    assert chat.state is ChatState.RECOVERING
    assert chat.unresolved_turn_pending


@pytest.mark.asyncio
async def test_duplicate_renderer_prefers_completed_owned_turn(monkeypatch):
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
    from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

    runtime, _, _ = recovery_runtime()
    chat = _chat()
    chat.runtime = runtime
    chat.state = ChatState.RECOVERING
    chat.active_turn_id = "owned"
    chat.provider_session_id = "conversation"
    chat.chat_url = "https://chatgpt.com/g/g-p-original/c/conversation"
    chat.target_id = "stale"
    pages = [{"pageHandle": handle, "targetId": handle, "url": chat.chat_url} for handle in ("stale", "complete")]

    def snapshot(handle):
        return ChatSnapshot(url=chat.chat_url, composer_present=True, composer_editable=True,
            user_count=1, assistant_count=1, latest_user_id="u1", user_message_ids=("u1",),
            latest_assistant_id="a1", latest_user_text="owned", latest_assistant_text="answer",
            terminal_witness_assistant_id="a1" if handle == "complete" else None,
            generating=handle == "stale", dom_signals=frozenset({"completion-control"}) if handle == "complete" else frozenset(), error_present=False)

    async def page_by_handle(handle):
        return SimpleNamespace(handle=handle)

    async def browser_snapshot(page, **kwargs):
        value = snapshot(page.handle)
        return {"url": value.url, "latestUserId": "u1", "userMessageIds": ["u1"],
                "latestAssistantId": "a1", "terminalWitnessAssistantId": value.terminal_witness_assistant_id,
                "generating": value.generating, "domSignals": {signal: True for signal in value.dom_signals}}

    async def chat_snapshot(**kwargs):
        return snapshot(chat.page_handle)

    async def find(*args, **kwargs):
        return pages[0]  # Preferred target is deliberately stale.

    runtime._gpt_browser = SimpleNamespace(page_by_handle=page_by_handle, snapshot=browser_snapshot)
    monkeypatch.setattr(runtime, "find_conversation_page", find)
    chat.snapshot = chat_snapshot
    await chat.reconcile(pages)
    assert chat.target_id == "complete"
    assert chat.state is ChatState.BUSY


@pytest.mark.asyncio
async def test_second_disconnect_during_rebind_is_not_lost(monkeypatch):
    runtime, chat, calls = recovery_runtime()
    connections = 0
    reconciliations = 0

    async def pages(method):
        return []

    async def stop():
        calls.append("replacement-stop")

    async def available():
        nonlocal connections
        connections += 1
        runtime._bridge = SimpleNamespace(call=pages, stop=stop)
        runtime.state = ProviderState.AVAILABLE

    async def reconcile(pages):
        nonlocal reconciliations
        reconciliations += 1
        if reconciliations == 1:
            runtime._disconnect_epoch += 1
        chat.state = "busy"

    chat.reconcile = reconcile
    monkeypatch.setattr(runtime, "ensure_available", available)
    await asyncio.wait_for(runtime.recover(), 1)
    assert connections == reconciliations == 2
    assert calls.count("replacement-stop") == 1
