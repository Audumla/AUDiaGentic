"""Persistent provider chat with disposable page binding."""

from __future__ import annotations

import asyncio
from enum import StrEnum

from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingSink,
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)

from .runtime import GptAutoProviderRuntime
from .snapshot import ChatSnapshot
from .urls import canonical_chat_url, parse_provider_session_id, url_matches_provider_session


class ChatState(StrEnum):
    OPENING = "opening"
    READY = "ready"
    BUSY = "busy"
    ACQUIRING_SESSION_ID = "acquiring-session-id"
    RECOVERING = "recovering"
    FAILED = "failed"
    CLOSED = "closed"


class PersistentChat:
    def __init__(
        self,
        *,
        ag_session_id: str,
        project_url: str,
        runtime: GptAutoProviderRuntime,
        binding_sink: ProviderSessionBindingSink,
        provider_session_id: str | None = None,
        chat_url: str | None = None,
    ) -> None:
        self.ag_session_id = ag_session_id
        self.project_url = project_url
        self.provider_session_id = provider_session_id
        self.chat_url = chat_url
        self.page_handle: str | None = None
        self.active_turn_id: str | None = None
        self.state = ChatState.OPENING
        self.runtime = runtime
        self.binding_sink = binding_sink
        self._lost_during_turn = False
        self._last_url: str | None = None

    async def open(self) -> None:
        await self.runtime.ensure_available()
        await self.runtime.register_chat(self)
        pages = await self.runtime.bridge.call("list_pages")
        target = self.chat_url if self.provider_session_id else self.project_url
        for page in pages:
            if self.provider_session_id and url_matches_provider_session(
                str(page.get("url") or ""), self.provider_session_id
            ):
                self.page_handle = str(page["pageHandle"])
                break
        if self.page_handle is None:
            result = await self.runtime.bridge.call(
                "create_window_page"
                if self.runtime.config.browser.dedicated_window
                else "create_page"
            )
            self.page_handle = str(result["pageHandle"])
            await self.runtime.bridge.call(
                "navigate",
                {
                    "pageHandle": self.page_handle,
                    "url": target,
                    "timeoutMs": int(self.runtime.config.chat.navigation_timeout_seconds * 1000),
                },
                timeout=self.runtime.config.chat.navigation_timeout_seconds + 2,
            )
        await self._wait_ready()
        snap = await self.snapshot()
        if self.provider_session_id and not url_matches_provider_session(
            snap.url, self.provider_session_id
        ):
            self.state = ChatState.FAILED
            raise RuntimeError("gpt-auto resumed page has conflicting provider session id")
        self.state = ChatState.READY

    async def _wait_ready(self) -> None:
        deadline = (
            asyncio.get_running_loop().time() + self.runtime.config.chat.ready_timeout_seconds
        )
        while asyncio.get_running_loop().time() < deadline:
            snap = await self.snapshot()
            if snap.composer_present:
                return
            await asyncio.sleep(0.25)
        raise RuntimeError("ChatGPT composer did not become ready")

    async def snapshot(self) -> ChatSnapshot:
        if self.state is ChatState.RECOVERING:
            deadline = (
                asyncio.get_running_loop().time() + self.runtime.config.cdp.recovery_timeout_seconds
            )
            while (
                self.state is ChatState.RECOVERING and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.05)
            if self.state is ChatState.RECOVERING:
                raise RuntimeError("gpt-auto chat recovery timed out")
        if not self.page_handle:
            raise RuntimeError("chat page is not bound")
        snapshot = ChatSnapshot.from_bridge(
            await self.runtime.bridge.call(
                "snapshot",
                {
                    "pageHandle": self.page_handle,
                    "signals": self.runtime.config.workflow.bridge_signals(),
                },
            )
        )
        self._last_url = snapshot.url
        return snapshot

    async def acquire_provider_identity(self, initial: ChatSnapshot | None = None) -> ChatSnapshot:
        self.state = ChatState.ACQUIRING_SESSION_ID
        deadline = (
            asyncio.get_running_loop().time() + self.runtime.config.chat.navigation_timeout_seconds
        )
        snap = initial
        while asyncio.get_running_loop().time() < deadline:
            snap = snap or await self.snapshot()
            provider_id = parse_provider_session_id(snap.url)
            if provider_id:
                chat_url = canonical_chat_url(snap.url)
                if not chat_url:
                    raise RuntimeError("ChatGPT conversation URL could not be canonicalized")
                result = self.binding_sink(
                    ProviderSessionBindingUpdate(
                        provider_session_ref=ProviderSessionRef(provider_id),
                        metadata={
                            "project-url": self.project_url,
                            "provider-session-id": provider_id,
                            "chat-url": chat_url,
                        },
                    )
                )
                if asyncio.iscoroutine(result):
                    await result
                self.provider_session_id = provider_id
                self.chat_url = chat_url
                self.state = ChatState.BUSY
                return snap
            snap = None
            await asyncio.sleep(0.2)
        self.state = ChatState.FAILED
        raise RuntimeError("ChatGPT accepted the turn but no provider session id appeared")

    async def page_lost(self, handle: str) -> None:
        if handle != self.page_handle:
            return
        self.page_handle = None
        self._lost_during_turn = self.active_turn_id is not None
        self.state = ChatState.RECOVERING
        pages = await self.runtime.bridge.call("list_pages")
        await self.reconcile(pages)

    async def reconcile(self, pages: list[dict]) -> None:
        if self.state is ChatState.CLOSED:
            return
        if self.provider_session_id:
            for page in pages:
                if url_matches_provider_session(
                    str(page.get("url") or ""), self.provider_session_id
                ):
                    self.page_handle = str(page["pageHandle"])
                    self.state = ChatState.BUSY if self.active_turn_id else ChatState.READY
                    return
            result = await self.runtime.bridge.call("create_page")
            self.page_handle = str(result["pageHandle"])
            await self.runtime.bridge.call(
                "navigate",
                {
                    "pageHandle": self.page_handle,
                    "url": self.chat_url,
                    "timeoutMs": int(self.runtime.config.chat.navigation_timeout_seconds * 1000),
                },
            )
            await self._wait_ready()
            self.state = ChatState.BUSY if self.active_turn_id else ChatState.READY
            return
        if self.active_turn_id:
            exact = [page for page in pages if page.get("url") == self._last_url]
            if len(exact) == 1:
                self.page_handle = str(exact[0]["pageHandle"])
                self.state = ChatState.BUSY
                return
            self.state = ChatState.FAILED
            return
        result = await self.runtime.bridge.call("create_page")
        self.page_handle = str(result["pageHandle"])
        await self.runtime.bridge.call(
            "navigate",
            {
                "pageHandle": self.page_handle,
                "url": self.project_url,
                "timeoutMs": int(self.runtime.config.chat.navigation_timeout_seconds * 1000),
            },
        )
        await self._wait_ready()
        self.state = ChatState.READY

    async def close(self) -> None:
        if self.state is ChatState.CLOSED:
            return
        handle, self.page_handle = self.page_handle, None
        self.state = ChatState.CLOSED
        self.runtime.unregister_chat(self)
        if handle:
            try:
                await self.runtime.bridge.call("close_page", {"pageHandle": handle})
            except Exception:
                pass
