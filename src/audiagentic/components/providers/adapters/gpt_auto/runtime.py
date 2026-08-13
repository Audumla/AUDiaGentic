"""Shared browser/CDP lifecycle authority for all gpt-auto chats."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import TYPE_CHECKING

from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .browser_process import BrowserProcessController
from .cdp.bridge import PythonCdpBridge
from .config import GptAutoConfig

if TYPE_CHECKING:
    from .chat import PersistentChat


class ProviderState(StrEnum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    STARTING = "starting"
    AVAILABLE = "available"
    RECOVERING = "recovering"
    FAILED = "failed"
    STOPPING = "stopping"


_ENGINE = TransitionEngine(
    TransitionConfig(
        transitions={
            "stopped": frozenset({"connecting"}),
            "connecting": frozenset({"available", "starting", "failed"}),
            "starting": frozenset({"connecting", "failed"}),
            "available": frozenset({"recovering", "stopping"}),
            "recovering": frozenset({"connecting", "starting", "failed"}),
            "failed": frozenset({"connecting", "stopping"}),
            "stopping": frozenset({"stopped"}),
        },
        terminal_states=frozenset(),
    )
)


class GptAutoProviderRuntime:
    def __init__(self, config: GptAutoConfig) -> None:
        self.config = config
        self.state = ProviderState.STOPPED
        self._lifecycle_lock = asyncio.Lock()
        self._bridge: PythonCdpBridge | None = None
        self._chats: dict[str, PersistentChat] = {}
        # A browser page is an execution resource.  Never let two live
        # provider sessions drive the same tab concurrently, even when both
        # happen to resolve the same project or ChatGPT URL.
        self._page_owners: dict[str, str] = {}
        self._event_task: asyncio.Task[None] | None = None
        self._dedicated_window_anchor: str | None = None
        self._browser = BrowserProcessController(config.browser, cdp_probe=self._cdp_available)

    @property
    def bridge(self) -> PythonCdpBridge:
        if not self._bridge:
            raise RuntimeError("gpt-auto provider runtime is unavailable")
        return self._bridge

    def _move(self, target: ProviderState) -> None:
        failure = _ENGINE.check(self.state.value, target.value)
        if failure:
            raise RuntimeError(f"illegal provider transition {self.state}->{target}: {failure}")
        self.state = target

    async def _cdp_available(self) -> bool:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self.config.browser.remote_debugging_port), 1
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    async def ensure_available(self) -> None:
        async with self._lifecycle_lock:
            if self.state is ProviderState.AVAILABLE and self._bridge:
                return
            if self.state in {ProviderState.STOPPED, ProviderState.FAILED}:
                self._move(ProviderState.CONNECTING)
            elif self.state is ProviderState.RECOVERING:
                self._move(ProviderState.CONNECTING)
            try:
                if not await self._cdp_available():
                    self._move(ProviderState.STARTING)
                    await self._browser.ensure_browser_for_cdp()
                    self._move(ProviderState.CONNECTING)
                bridge = PythonCdpBridge(self.config)
                await bridge.start()
                self._bridge = bridge
                self._move(ProviderState.AVAILABLE)
                self._event_task = asyncio.create_task(self._route_events(bridge))
            except Exception:
                if self.state in {ProviderState.CONNECTING, ProviderState.STARTING}:
                    self._move(ProviderState.FAILED)
                raise

    async def ensure_dedicated_window_anchor(self) -> str:
        """Create one persistent anchor tab for the shared GPT-auto window."""
        await self.ensure_available()
        if self._dedicated_window_anchor:
            try:
                pages = await self.bridge.call("list_pages")
                if any(str(p.get("pageHandle")) == self._dedicated_window_anchor for p in pages):
                    return self._dedicated_window_anchor
            except Exception:
                pass
            self._dedicated_window_anchor = None
        page = await self.bridge.call("create_window_page")
        self._dedicated_window_anchor = str(page["pageHandle"])
        return self._dedicated_window_anchor

    async def _route_events(self, bridge: PythonCdpBridge) -> None:
        while self._bridge is bridge:
            event = await bridge.events.get()
            if event.name in {"browser_disconnected", "helper_disconnected"}:
                asyncio.create_task(self.recover())
                return
            if event.page_handle:
                for chat in tuple(self._chats.values()):
                    if chat.page_handle == event.page_handle:
                        await chat.page_lost(event.page_handle)

    async def recover(self) -> None:
        async with self._lifecycle_lock:
            if self.state is not ProviderState.AVAILABLE:
                return
            self._move(ProviderState.RECOVERING)
            old, self._bridge = self._bridge, None
            if old:
                await old.stop()
        await self.ensure_available()
        pages = await self.bridge.call("list_pages")
        for chat in tuple(self._chats.values()):
            await chat.reconcile(pages)

    async def register_chat(self, chat: PersistentChat) -> None:
        existing = self._chats.get(chat.ag_session_id)
        if existing is not None and existing is not chat:
            raise RuntimeError("duplicate gpt-auto gateway session")
        self._chats[chat.ag_session_id] = chat

    def claim_page(self, chat: PersistentChat, page_handle: str) -> bool:
        owner = self._page_owners.get(page_handle)
        if owner is not None and owner != chat.ag_session_id:
            return False
        self._page_owners[page_handle] = chat.ag_session_id
        return True

    def release_page(self, chat: PersistentChat, page_handle: str | None) -> None:
        if page_handle and self._page_owners.get(page_handle) == chat.ag_session_id:
            self._page_owners.pop(page_handle, None)

    def unregister_chat(self, chat: PersistentChat) -> None:
        if self._chats.get(chat.ag_session_id) is chat:
            self._chats.pop(chat.ag_session_id, None)
        self.release_page(chat, chat.page_handle)

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if self.state is ProviderState.STOPPED:
                return
            if self.state is ProviderState.AVAILABLE:
                self._move(ProviderState.STOPPING)
            elif self.state in {ProviderState.FAILED}:
                self._move(ProviderState.STOPPING)
            for chat in tuple(self._chats.values()):
                await chat.close()
            if self._dedicated_window_anchor and self._bridge:
                try:
                    await self._bridge.call(
                        "close_page", {"pageHandle": self._dedicated_window_anchor}
                    )
                except Exception:
                    pass
                self._dedicated_window_anchor = None
            if self._bridge:
                await self._bridge.stop()
                self._bridge = None
            await self._browser.shutdown()
            if self._event_task and not self._event_task.done():
                self._event_task.cancel()
            self._move(ProviderState.STOPPED)
