"""Shared browser/CDP lifecycle authority for all gpt-auto chats."""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .browser_process import BrowserProcessController
from .cdp.bridge import PythonCdpBridge
from .config import GptAutoConfig
from .gpt_auto_cdp import GptAutoCdpBrowserController
from .status.status_page import STATUS_PAGE_URL, render_status_page
from .urls import url_matches_provider_session

if TYPE_CHECKING:
    from .chat import PersistentChat


logger = logging.getLogger(__name__)


def _compact_row(row: dict[str, object]) -> dict[str, object]:
    """Drop absent dashboard fields without dropping meaningful false/zero."""
    return {
        key: value
        for key, value in row.items()
        if value is not None and value != "" and value != {} and value != []
    }


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
            "connecting": frozenset({"available", "starting", "failed", "stopping"}),
            "starting": frozenset({"connecting", "failed", "stopping"}),
            "available": frozenset({"recovering", "stopping"}),
            "recovering": frozenset({"connecting", "starting", "failed", "stopping"}),
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
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._bridge: PythonCdpBridge | None = None
        self._gpt_browser: GptAutoCdpBrowserController | None = None
        self._chats: dict[str, PersistentChat] = {}
        # A browser page is an execution resource.  Never let two live
        # provider sessions drive the same tab concurrently, even when both
        # happen to resolve the same project or ChatGPT URL.
        self._page_owners: dict[str, str] = {}
        self._conversation_owners: dict[str, str] = {}
        self._event_task: asyncio.Task[None] | None = None
        self._status_refresh_task: asyncio.Task[None] | None = None
        self._dedicated_window_anchor: str | None = None
        self._dedicated_window_id: int | None = None
        self._dedicated_window_lock = asyncio.Lock()
        self._browser = BrowserProcessController(config.browser, cdp_probe=self._cdp_available)

    @property
    def bridge(self) -> PythonCdpBridge:
        if not self._bridge:
            raise RuntimeError("gpt-auto provider runtime is unavailable")
        return self._bridge

    @property
    def gpt_browser(self) -> GptAutoCdpBrowserController:
        if self._gpt_browser is None:
            raise RuntimeError("gpt-auto browser adapter is unavailable")
        return self._gpt_browser

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
        self._owner_loop = asyncio.get_running_loop()
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
                bridge = await self._connect_bridge()
                self._bridge = bridge
                self._gpt_browser = GptAutoCdpBrowserController(bridge)
                self._move(ProviderState.AVAILABLE)
                self._event_task = asyncio.create_task(self._route_events(bridge))
                self._status_refresh_task = asyncio.create_task(self._status_refresh_loop())
            except Exception:
                if self.state in {ProviderState.CONNECTING, ProviderState.STARTING}:
                    self._move(ProviderState.FAILED)
                raise

    async def _connect_bridge(self) -> PythonCdpBridge:
        """Connect only after the CDP endpoint is actually ready.

        Browser process creation and DevTools readiness are distinct states.
        Keep that transient retry policy in the runtime lifecycle boundary,
        rather than leaking it into session/chat workflows.
        """
        deadline = asyncio.get_running_loop().time() + self.config.cdp.connect_timeout_seconds
        delay = 0.05
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            bridge = PythonCdpBridge(self.config)
            try:
                remaining = max(0.01, deadline - asyncio.get_running_loop().time())
                await bridge.start(connect_timeout=remaining)
                return bridge
            except Exception as exc:  # endpoint may still be starting
                last_error = exc
                await bridge.stop()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 0.5)
        raise RuntimeError(
            "CDP endpoint did not become ready before connect timeout"
        ) from last_error

    async def ensure_dedicated_window_anchor(self) -> str:
        """Create one persistent anchor tab for the shared GPT-auto window."""
        async with self._dedicated_window_lock:
            await self.ensure_available()
            pages = await self.bridge.call("list_pages")
            if self._dedicated_window_anchor and any(
                str(p.get("pageHandle")) == self._dedicated_window_anchor for p in pages
            ):
                anchor_page = next(
                    p for p in pages if str(p.get("pageHandle")) == self._dedicated_window_anchor
                )
                self._dedicated_window_id = _window_id(anchor_page)
                return self._dedicated_window_anchor
            # Gateway/runtime recovery can lose the in-memory handle while the
            # browser tab survives. Reuse the first existing dashboard anchor.
            existing = next(
                (str(p["pageHandle"]) for p in pages if str(p.get("url") or "") == STATUS_PAGE_URL),
                None,
            )
            if existing:
                self._dedicated_window_anchor = existing
                self._dedicated_window_id = _window_id(
                    next(p for p in pages if str(p.get("pageHandle")) == existing)
                )
                await self.refresh_status_page()
                return existing
            self._dedicated_window_anchor = None
            page = await self.bridge.call("create_window_page")
            self._dedicated_window_anchor = str(page["pageHandle"])
            self._dedicated_window_id = _window_id(page)
            await self.bridge.call(
                "navigate",
                {
                    "pageHandle": self._dedicated_window_anchor,
                    "url": STATUS_PAGE_URL,
                },
            )
            await self.refresh_status_page()
            return self._dedicated_window_anchor

    async def refresh_status_page(self) -> None:
        """Render current shared-runtime/session facts in the anchor tab."""
        if not self._dedicated_window_anchor or not self._bridge:
            return
        rows = [
            _compact_row(
                {
                    "provider": "gpt-auto",
                    "session": chat.ag_session_id,
                    "project": chat.project_name,
                    "state": chat.state.value,
                    "page": chat.page_handle,
                    "turn": chat.active_turn_id,
                    "observed": getattr(chat, "observed_status", lambda: {})(),
                }
            )
            for chat in self._chats.values()
        ]
        payload = {
            "runtime": self.state.value,
            "providers": [{"provider_id": "gpt-auto", "state": self.state.value}],
            "sessions": rows,
            "queue": {
                "running": sum(
                    1 for row in rows if row["state"] in {"busy", "generating", "running"}
                ),
                "queued": 0,
            },
            "updated": asyncio.get_running_loop().time(),
        }
        try:
            await render_status_page(self.bridge, self._dedicated_window_anchor, payload)
        except Exception:
            # The dashboard is observability only. A stale/closed anchor must
            # never prevent a provider session from opening or completing.
            self._dedicated_window_anchor = None
            self._dedicated_window_id = None

    async def _status_refresh_loop(self) -> None:
        """Keep the operator projection live between event-driven updates.

        CDP pages do not have a gateway endpoint to poll (the dashboard is a
        data URL), so the shared runtime periodically pushes a fresh snapshot.
        The loop is observability-only and is cancelled with the runtime.
        """
        try:
            while self._bridge is not None:
                await asyncio.sleep(1.0)
                await self.refresh_status_page()
        except asyncio.CancelledError:
            raise

    async def _route_events(self, bridge: PythonCdpBridge) -> None:
        while self._bridge is bridge:
            event = await bridge.events.get()
            if event.name in {"browser_disconnected", "helper_disconnected"}:
                asyncio.create_task(self.recover())
                return
            # Navigation, target metadata changes and lifecycle notifications
            # are normal page activity.  Only bridge-classified terminal
            # target loss may invalidate a chat's page binding.
            if event.name in {"page_closed", "page_crashed"} and event.page_handle:
                for chat in tuple(self._chats.values()):
                    if chat.page_handle == event.page_handle:
                        try:
                            await chat.page_lost(event.page_handle)
                        except Exception:  # noqa: BLE001 - isolate one chat from the router
                            self._mark_chat_failed(chat)
                            logger.exception(
                                "gpt-auto page recovery failed",
                                extra={"session-id": chat.ag_session_id},
                            )

    async def recover(self) -> None:
        async with self._lifecycle_lock:
            if self.state is not ProviderState.AVAILABLE:
                return
            self._move(ProviderState.RECOVERING)
            old, self._bridge = self._bridge, None
            self._gpt_browser = None
            # Handles are allocated by each bridge instance. Never carry a
            # handle or ownership claim into the next bridge generation.
            self._dedicated_window_anchor = None
            self._dedicated_window_id = None
            self._page_owners.clear()
            for chat in tuple(self._chats.values()):
                chat.bridge_replaced()
            if old:
                await old.stop()
        await self.ensure_available()
        pages = await self.bridge.call("list_pages")
        for chat in tuple(self._chats.values()):
            if chat.active_turn_id is None:
                # A shared CDP-bridge fault genuinely invalidates every
                # chat's bridge-local page handle (bridge_replaced(), above,
                # already covers that for all chats) -- but that does not
                # mean every otherwise-idle chat needs to pay the cost of
                # reconciling right now. Idle chats already have a lazy
                # RECOVERING -> reconcile path in ensure_ready(); let them
                # take it on their own next admission instead of driving
                # every registered chat across every project through
                # reconcile() here, which would let one project's bridge
                # fault stall every other unrelated project sharing the
                # runtime.
                continue
            try:
                await chat.reconcile(pages)
            except Exception:  # noqa: BLE001 - isolate one session's recovery
                self._mark_chat_failed(chat)
                logger.exception(
                    "gpt-auto bridge recovery failed for session",
                    extra={"session-id": chat.ag_session_id},
                )

    @staticmethod
    def _mark_chat_failed(chat: PersistentChat) -> None:
        mark_failed = getattr(chat, "mark_recovery_failed", None)
        if mark_failed is not None:
            mark_failed()

    async def create_chat_page(self) -> str:
        """Create a session page through the one shared-window admission path."""
        if self.config.browser.dedicated_window:
            anchor = await self.ensure_dedicated_window_anchor()
            page = await self.bridge.call("create_page_in_window", {"anchorPageHandle": anchor})
        else:
            page = await self.bridge.call("create_page")
        return str(page["pageHandle"])

    async def find_conversation_page(
        self,
        provider_session_id: str,
        *,
        preferred_target_id: str | None = None,
    ) -> dict | None:
        """Re-establish window identity, then find one retained conversation page."""
        if self.config.browser.dedicated_window:
            await self.ensure_dedicated_window_anchor()
        pages = await self.bridge.call("list_pages")
        if preferred_target_id:
            preferred = next(
                (
                    page
                    for page in pages
                    if str(page.get("targetId") or "") == preferred_target_id
                    and self.page_belongs_to_dedicated_window(page)
                    and url_matches_provider_session(
                        str(page.get("url") or ""),
                        provider_session_id,
                    )
                ),
                None,
            )
            if preferred is not None:
                return preferred
        matches = [
            page
            for page in pages
            if self.page_belongs_to_dedicated_window(page)
            and url_matches_provider_session(
                str(page.get("url") or ""),
                provider_session_id,
            )
        ]
        if len(matches) > 1:
            raise RuntimeError(
                "gpt-auto retained conversation is ambiguous across multiple managed tabs"
            )
        return matches[0] if matches else None

    async def page_record(self, page_handle: str) -> dict | None:
        """Return the current bridge record for a handle without changing ownership."""
        pages = await self.bridge.call("list_pages")
        return next(
            (page for page in pages if str(page.get("pageHandle") or "") == page_handle),
            None,
        )

    def page_belongs_to_dedicated_window(self, page: dict) -> bool:
        """Constrain resume/recovery candidates to the managed GPT window."""
        return not self.config.browser.dedicated_window or (
            self._dedicated_window_id is not None and _window_id(page) == self._dedicated_window_id
        )

    async def register_chat(self, chat: PersistentChat) -> None:
        existing = self._chats.get(chat.ag_session_id)
        if existing is not None and existing is not chat:
            raise RuntimeError("duplicate gpt-auto gateway session")
        provider_id = chat.provider_session_id
        if provider_id:
            owner = self._conversation_owners.get(provider_id)
            if owner is not None and owner != chat.ag_session_id:
                prior = self._chats.get(owner)
                if prior is None or _chat_terminal(prior):
                    self._conversation_owners.pop(provider_id, None)
                else:
                    raise RuntimeError("gpt-auto provider conversation is already owned")
            self._conversation_owners[provider_id] = chat.ag_session_id
        self._chats[chat.ag_session_id] = chat
        await self.refresh_status_page()

    def claim_conversation(self, chat: PersistentChat, provider_session_id: str) -> bool:
        owner = self._conversation_owners.get(provider_session_id)
        if owner is not None and owner != chat.ag_session_id:
            prior = self._chats.get(owner)
            if prior is None or _chat_terminal(prior):
                self._conversation_owners.pop(provider_session_id, None)
            else:
                return False
        self._conversation_owners[provider_session_id] = chat.ag_session_id
        return True

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
        if chat.provider_session_id and self._conversation_owners.get(chat.provider_session_id) == chat.ag_session_id:
            self._conversation_owners.pop(chat.provider_session_id, None)
        if getattr(self, "_dedicated_window_anchor", None) and self._bridge:
            asyncio.create_task(self.refresh_status_page())

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if self.state is ProviderState.STOPPED:
                return
            if self.state is ProviderState.AVAILABLE:
                self._move(ProviderState.STOPPING)
            elif self.state in {
                ProviderState.CONNECTING,
                ProviderState.STARTING,
                ProviderState.FAILED,
                ProviderState.RECOVERING,
            }:
                self._move(ProviderState.STOPPING)
            for chat in tuple(self._chats.values()):
                await chat.close()
            if (
                self._dedicated_window_anchor
                and self._bridge
                and self.config.browser.close_tabs_on_session_close
            ):
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
                self._gpt_browser = None
            # Normal gateway/runtime teardown detaches CDP but preserves a
            # provider-launched browser.  Durable conversation tabs must
            # survive process restarts; terminating the browser is an explicit
            # destructive operation through shutdown_browser().
            if self._event_task and not self._event_task.done():
                self._event_task.cancel()
            if self._status_refresh_task and not self._status_refresh_task.done():
                self._status_refresh_task.cancel()
            self._status_refresh_task = None
            self._move(ProviderState.STOPPED)

    async def shutdown_browser(self) -> None:
        """Explicitly terminate only a browser process this runtime launched."""
        await self.shutdown()
        await self._browser.shutdown()

    async def shutdown_from_owner(self) -> None:
        """Marshal teardown to the loop that owns CDP transports and locks."""
        owner = self._owner_loop
        current = asyncio.get_running_loop()
        if owner is None or owner is current or not owner.is_running():
            await self.shutdown()
            return
        future = asyncio.run_coroutine_threadsafe(self.shutdown(), owner)
        await asyncio.wrap_future(future)


def _window_id(page: dict) -> int | None:
    value = page.get("windowId")
    return int(value) if value is not None else None


def _chat_terminal(chat: PersistentChat) -> bool:
    """Whether a retained provider owner can no longer make progress."""
    state = getattr(chat, "state", None)
    return getattr(state, "value", state) in {"failed", "closed"}
