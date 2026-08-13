from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.components.providers.adapters.gpt_auto.cdp.bridge import BridgeEvent
from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime import (
    GptAutoProviderRuntime,
    ProviderState,
)
from audiagentic.components.providers.adapters.gpt_auto import runtime as runtime_module

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
        ag_session_id="session-a", project_name="project", project_url=None,
        runtime=runtime, config=runtime.config, binding_sink=lambda _update: None,
    )
    await first.open()
    assert first.page_handle == "page-1"

    second = PersistentChat(
        ag_session_id="session-b", project_name="project", project_url=None,
        runtime=runtime, config=runtime.config, binding_sink=lambda _update: None,
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


async def _done() -> None:
    return None


async def _pages():
    return [{"pageHandle": "page-1", "targetId": "new-target"}]
