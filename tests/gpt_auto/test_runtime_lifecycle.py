from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto import runtime as runtime_module
from audiagentic.components.providers.adapters.gpt_auto.cdp.bridge import BridgeEvent
from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime import (
    GptAutoProviderRuntime,
    ProviderState,
)
from audiagentic.components.providers.adapters.gpt_auto.status.status_page import STATUS_PAGE_URL
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_greenfield_config_urls import valid_config


class _EventBridge:
    def __init__(self) -> None:
        self.events: asyncio.Queue[BridgeEvent] = asyncio.Queue()


@pytest.mark.asyncio
async def test_runtime_routes_only_terminal_page_events_to_page_loss() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    bridge = _EventBridge()
    runtime._bridge = bridge  # type: ignore[assignment]
    runtime.state = ProviderState.AVAILABLE
    chat = SimpleNamespace(page_handle="page-1", lost=[])

    async def page_lost(handle: str) -> None:
        chat.lost.append(handle)

    chat.page_lost = page_lost
    runtime._chats = {"session-1": chat}
    task = asyncio.create_task(runtime._route_events(bridge))  # type: ignore[arg-type]
    try:
        await bridge.events.put(BridgeEvent("target_changed", "page-1"))
        await bridge.events.put(BridgeEvent("page_lifecycle", "page-1"))
        await asyncio.sleep(0)
        assert chat.lost == []

        await bridge.events.put(BridgeEvent("page_closed", "page-1"))
        await asyncio.sleep(0)
        assert chat.lost == ["page-1"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class _Page:
    handle = "page-1"


class _GptBrowser:
    def __init__(self) -> None:
        self.closed: list[_Page] = []

    async def open_project_page(self, **_kwargs):
        return {"page": _Page(), "projectUrl": "https://chatgpt.com/g/g-p-project/project"}

    async def close(self, page: _Page) -> None:
        self.closed.append(page)


class _OpenRuntime:
    def __init__(self) -> None:
        config = valid_config()
        config["browser"]["dedicated-window"] = False
        self.config = GptAutoConfig.from_dict(config)
        self.gpt_browser = _GptBrowser()
        self._owners: dict[str, str] = {}

    async def ensure_available(self) -> None:
        return None

    async def register_chat(self, _chat) -> None:
        return None

    def unregister_chat(self, _chat) -> None:
        return None

    def claim_page(self, chat, page_handle: str) -> bool:
        owner = self._owners.get(page_handle)
        if owner and owner != chat.ag_session_id:
            return False
        self._owners[page_handle] = chat.ag_session_id
        return True


@pytest.mark.asyncio
async def test_fast_open_claims_page_before_ready_and_rejects_second_session() -> None:
    runtime = _OpenRuntime()
    first = PersistentChat(
        ag_session_id="session-a",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=runtime.config,
        binding_sink=lambda _update: None,
    )
    await first.open()
    assert first.page_handle == "page-1"

    second = PersistentChat(
        ag_session_id="session-b",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=runtime.config,
        binding_sink=lambda _update: None,
    )
    with pytest.raises(RuntimeError, match="already owned"):
        await second.open()
    assert len(runtime.gpt_browser.closed) == 1


@pytest.mark.asyncio
async def test_runtime_waits_for_cdp_endpoint_after_browser_launch(monkeypatch) -> None:
    attempts: list[str] = []

    class _Bridge:
        def __init__(self, _config) -> None:
            attempts.append("new")

        async def start(self, **_kwargs) -> None:
            if attempts.count("new") < 3:
                raise OSError("connection refused")

        async def stop(self) -> None:
            attempts.append("stop")

    monkeypatch.setattr(runtime_module, "PythonCdpBridge", _Bridge)
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    bridge = await runtime._connect_bridge()
    assert isinstance(bridge, _Bridge)
    assert attempts.count("new") == 3
    assert attempts.count("stop") == 2


@pytest.mark.asyncio
async def test_runtime_shutdown_is_legal_during_connection_start() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.CONNECTING
    await runtime.shutdown()
    assert runtime.state is ProviderState.STOPPED


@pytest.mark.asyncio
async def test_chat_recovery_retains_page_after_recoverable_turn_failure() -> None:
    config = GptAutoConfig.from_dict(valid_config())

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 0,
                "assistantCount": 0,
                "domSignals": {},
                "errorPresent": False,
            }

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=SimpleNamespace(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-recover",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.FAILED

    retained = await chat.retain_after_turn_failure(
        AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="prompt proof was ambiguous",
            details={"submission-ambiguous": True},
        )
    )

    assert retained is True
    assert chat.state.value == "ready"
    assert chat.page_handle == "page-1"


@pytest.mark.asyncio
async def test_chat_readiness_requires_two_stable_quiescent_snapshots() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    values = iter(
        [
            {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "generating": True,
                "userCount": 1,
                "assistantCount": 0,
                "domSignals": {"stop-control": True},
            },
            {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "generating": False,
                "userCount": 1,
                "assistantCount": 1,
                "latestAssistantId": "a1",
                "latestAssistantText": "done",
                "domSignals": {},
            },
            {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "generating": False,
                "userCount": 1,
                "assistantCount": 1,
                "latestAssistantId": "a1",
                "latestAssistantText": "done",
                "domSignals": {},
            },
        ]
    )

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return next(values)

    runtime = SimpleNamespace(gpt_browser=_Browser(), bridge=SimpleNamespace())
    chat = PersistentChat(
        ag_session_id="session-quiescent",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.RECOVERING

    result = await chat.wait_quiescent(allow_recovering=True)

    assert result.latest_assistant_text == "done"


@pytest.mark.asyncio
async def test_chat_close_retains_tab_by_default_for_gateway_resume() -> None:
    config = GptAutoConfig.from_dict(valid_config())

    class _Bridge:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call(self, method: str, params: dict) -> None:
            self.calls.append((method, params))

    bridge = _Bridge()
    runtime = SimpleNamespace(
        bridge=bridge,
        config=config,
        release_page=lambda _chat, _handle: None,
        unregister_chat=lambda _chat: None,
    )
    chat = PersistentChat(
        ag_session_id="session-retain",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.READY

    await chat.close()

    assert chat.state is ChatState.CLOSED
    assert chat.page_handle is None
    assert bridge.calls == []


@pytest.mark.asyncio
async def test_chat_close_can_opt_in_to_closing_tab() -> None:
    value = valid_config()
    value["browser"]["close-tabs-on-session-close"] = True
    config = GptAutoConfig.from_dict(value)

    class _Bridge:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call(self, method: str, params: dict) -> None:
            self.calls.append((method, params))

    bridge = _Bridge()
    runtime = SimpleNamespace(
        bridge=bridge,
        config=config,
        release_page=lambda _chat, _handle: None,
        unregister_chat=lambda _chat: None,
    )
    chat = PersistentChat(
        ag_session_id="session-close-tab",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.READY

    await chat.close()

    assert bridge.calls == [("close_page", {"pageHandle": "page-1"})]


@pytest.mark.asyncio
async def test_recovery_invalidates_bridge_local_handles_before_reconciliation(monkeypatch) -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    old = SimpleNamespace(stop=lambda: _done())
    replacement = SimpleNamespace(call=lambda method: _pages() if method == "list_pages" else None)
    runtime._bridge = old
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_anchor = "page-1"
    runtime._page_owners = {"page-1": "session-a"}
    chat = SimpleNamespace(replaced=0, reconciled=None)

    def bridge_replaced() -> None:
        chat.replaced += 1

    async def reconcile(pages) -> None:
        chat.reconciled = pages

    chat.bridge_replaced = bridge_replaced
    chat.reconcile = reconcile
    runtime._chats = {"session-a": chat}

    async def ensure_available() -> None:
        runtime._bridge = replacement
        runtime._gpt_browser = SimpleNamespace()
        runtime.state = ProviderState.AVAILABLE

    monkeypatch.setattr(runtime, "ensure_available", ensure_available)
    await runtime.recover()

    assert chat.replaced == 1
    assert chat.reconciled == [{"pageHandle": "page-1", "targetId": "new-target"}]
    assert runtime._page_owners == {}
    assert runtime._dedicated_window_anchor is None


def test_dedicated_window_ownership_rejects_duplicate_url_in_manual_window() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime._dedicated_window_id = 41

    assert runtime.page_belongs_to_dedicated_window({"windowId": 41})
    assert not runtime.page_belongs_to_dedicated_window({"windowId": 99})


@pytest.mark.asyncio
async def test_find_conversation_page_restores_window_before_selecting_retained_tab(
    monkeypatch,
) -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    calls: list[str] = []

    async def ensure_anchor() -> str:
        calls.append("anchor")
        runtime._dedicated_window_id = 7
        return "anchor"

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            calls.append("pages")
            return [
                {
                    "pageHandle": "manual-copy",
                    "targetId": "target-manual",
                    "windowId": 99,
                    "url": "https://chatgpt.com/c/provider-session",
                },
                {
                    "pageHandle": "retained",
                    "targetId": "target-retained",
                    "windowId": 7,
                    "url": "https://chatgpt.com/c/provider-session",
                },
            ]

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    monkeypatch.setattr(runtime, "ensure_dedicated_window_anchor", ensure_anchor)

    page = await runtime.find_conversation_page(
        "provider-session",
        preferred_target_id="target-retained",
    )

    assert calls == ["anchor", "pages"]
    assert page is not None
    assert page["pageHandle"] == "retained"


@pytest.mark.asyncio
async def test_reconcile_proves_quiescence_before_ready(monkeypatch) -> None:
    config = GptAutoConfig.from_dict(valid_config())
    page = {
        "pageHandle": "retained",
        "targetId": "target-retained",
        "url": "https://chatgpt.com/c/provider-session",
    }

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [page]

    async def find_page(_provider_session_id, *, preferred_target_id=None):
        return page

    runtime = SimpleNamespace(
        bridge=_Bridge(),
        find_conversation_page=find_page,
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-recovering",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
    )
    chat.state = ChatState.RECOVERING
    observed: list[bool] = []

    async def quiescent(*, allow_recovering=False):
        observed.append(allow_recovering)
        return SimpleNamespace()

    monkeypatch.setattr(chat, "wait_quiescent", quiescent)

    await chat.ensure_ready()

    assert observed == [True]
    assert chat.state is ChatState.READY
    assert chat.page_handle == "retained"
    assert chat.target_id == "target-retained"


@pytest.mark.asyncio
async def test_active_reconcile_prefers_stable_target_before_stale_url() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    runtime = SimpleNamespace(
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-active-recovery",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.state = ChatState.RECOVERING
    chat.active_turn_id = "turn-1"
    chat.target_id = "stable-target"
    chat._last_url = "https://chatgpt.com/g/g-p-project/project"

    await chat.reconcile(
        [
            {
                "pageHandle": "replacement-handle",
                "targetId": "stable-target",
                "url": "https://chatgpt.com/g/g-p-project/c/new-conversation",
            }
        ]
    )

    assert chat.page_handle == "replacement-handle"
    assert chat.target_id == "stable-target"
    assert chat.state is ChatState.BUSY


@pytest.mark.asyncio
async def test_lazy_recovery_reacquires_ambiguous_first_turn_target(monkeypatch) -> None:
    config = GptAutoConfig.from_dict(valid_config())
    runtime = SimpleNamespace(
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-ambiguous-first-turn",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.state = ChatState.RECOVERING
    chat.target_id = "retained-target"
    chat.active_turn_id = None
    observed: list[bool] = []

    async def quiescent(*, allow_recovering=False):
        observed.append(allow_recovering)
        return SimpleNamespace()

    monkeypatch.setattr(chat, "wait_quiescent", quiescent)

    await chat.reconcile(
        [
            {
                "pageHandle": "retained-handle",
                "targetId": "retained-target",
                "url": "https://chatgpt.com/g/g-p-project/c/new-conversation",
            }
        ]
    )

    assert observed == [True]
    assert chat.page_handle == "retained-handle"
    assert chat.state is ChatState.READY


@pytest.mark.asyncio
async def test_anchor_rediscovery_uses_immutable_url_not_mutable_title(monkeypatch) -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [
                {
                    "pageHandle": "manual",
                    "url": "data:text/html,other",
                    "title": "GPT-auto",
                    "windowId": 1,
                },
                {
                    "pageHandle": "anchor",
                    "url": STATUS_PAGE_URL,
                    "title": "Agent gateway · available",
                    "windowId": 7,
                },
            ]

    runtime._bridge = _Bridge()  # type: ignore[assignment]

    async def available():
        return None

    async def refreshed():
        return None

    monkeypatch.setattr(runtime, "ensure_available", available)
    monkeypatch.setattr(runtime, "refresh_status_page", refreshed)

    assert await runtime.ensure_dedicated_window_anchor() == "anchor"
    assert runtime._dedicated_window_id == 7


async def _done() -> None:
    return None


async def _pages():
    return [{"pageHandle": "page-1", "targetId": "new-target"}]
