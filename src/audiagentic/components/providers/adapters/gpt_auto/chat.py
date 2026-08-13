"""Persistent provider chat with disposable page binding."""

from __future__ import annotations

import asyncio
from enum import StrEnum

from audiagentic.foundation.contracts.errors import AudiaGenticError

from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingSink,
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)
from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .runtime import GptAutoProviderRuntime
from .config import GptAutoConfig
from .snapshot import ChatSnapshot
from .urls import (
    canonical_chat_url,
    canonical_project_url,
    parse_project_id,
    parse_provider_session_id,
    url_matches_provider_session,
)

class ChatState(StrEnum):
    OPENING = "opening"
    READY = "ready"
    BUSY = "busy"
    ACQUIRING_SESSION_ID = "acquiring-session-id"
    RECOVERING = "recovering"
    FAILED = "failed"
    CLOSED = "closed"


_CHAT_ENGINE = TransitionEngine(
    TransitionConfig(
        transitions={
            "opening": frozenset({"ready", "recovering", "failed", "closed"}),
            "ready": frozenset({"busy", "acquiring-session-id", "recovering", "failed", "closed"}),
            "busy": frozenset({"ready", "acquiring-session-id", "recovering", "failed", "closed"}),
            "acquiring-session-id": frozenset({"busy", "recovering", "failed", "closed"}),
            "recovering": frozenset({"ready", "busy", "failed", "closed"}),
            "failed": frozenset({"recovering", "closed"}),
        },
        terminal_states=frozenset({"closed"}),
        values=frozenset(state.value for state in ChatState),
    )
)


class PersistentChat:
    def __init__(
        self,
        *,
        ag_session_id: str,
        project_name: str,
        project_url: str | None,
        runtime: GptAutoProviderRuntime,
        config: GptAutoConfig,
        binding_sink: ProviderSessionBindingSink,
        provider_session_id: str | None = None,
        chat_url: str | None = None,
    ) -> None:
        self.ag_session_id = ag_session_id
        self.project_name = project_name
        self.project_url = project_url
        self.provider_session_id = provider_session_id
        self.chat_url = chat_url
        self.page_handle: str | None = None
        self.active_turn_id: str | None = None
        self.state = ChatState.OPENING
        self.runtime = runtime
        self.config = config
        self.binding_sink = binding_sink
        self._lost_during_turn = False
        self._last_url: str | None = None
        self._last_snapshot: ChatSnapshot | None = None
        self._recovery_ready = asyncio.Event()
        self._recovery_ready.set()

    def _claim_page(self, page_handle: str) -> bool:
        """Claim a page when the runtime exposes ownership tracking.

        The fallback keeps small adapter test doubles compatible while the
        production runtime always supplies the exclusive ownership method.
        """
        claim = getattr(self.runtime, "claim_page", None)
        return True if claim is None else bool(claim(self, page_handle))

    def _move(self, target: ChatState) -> None:
        failure = _CHAT_ENGINE.check(self.state.value, target.value)
        if failure:
            raise RuntimeError(f"illegal gpt-auto chat transition {self.state}->{target}: {failure}")
        self.state = target
        if target is ChatState.RECOVERING:
            self._recovery_ready.clear()
        else:
            self._recovery_ready.set()

    def _gpt_browser(self):
        browser = getattr(self.runtime, "gpt_browser", None)
        return browser if browser is not None else self.runtime.bridge

    async def open(self) -> None:
        """Open transactionally; release every resource on partial failure."""
        try:
            await self._open_impl()
        except BaseException:
            try:
                await self.close()
            except BaseException:  # noqa: BLE001 - preserve the original open error
                pass
            raise

    async def _open_impl(self) -> None:
        await self.runtime.ensure_available()
        await self.runtime.register_chat(self)
        browser = self._gpt_browser()
        composite_open = getattr(browser, "open_project_page", None)
        if self.provider_session_id is None and composite_open is not None:
            anchor = None
            if self.config.browser.dedicated_window:
                ensure_anchor = getattr(self.runtime, "ensure_dedicated_window_anchor", None)
                if ensure_anchor is not None:
                    anchor = await ensure_anchor()
            result = await composite_open(
                project_name=self.project_name,
                project_url=self.project_url,
                anchor_page=await browser.page(anchor) if anchor else None,
                navigation_timeout=self.config.chat.navigation_timeout_seconds,
                ready_timeout=self.config.chat.ready_timeout_seconds,
            )
            self.page_handle = result["page"].handle
            self.project_url = str(result["projectUrl"])
            if not self._claim_page(self.page_handle):
                try:
                    await browser.close(result["page"])
                finally:
                    self.page_handle = None
                    self._move(ChatState.FAILED)
                    self.runtime.unregister_chat(self)
                raise RuntimeError("gpt-auto opened a page already owned by another session")
            self._move(ChatState.READY)
            return
        pages = await self.runtime.bridge.call("list_pages")
        target = self.chat_url if self.provider_session_id else self.project_url
        for page in pages:
            if (
                self.provider_session_id
                and url_matches_provider_session(
                    str(page.get("url") or ""), self.provider_session_id
                )
                and self._claim_page(str(page["pageHandle"]))
            ):
                self.page_handle = str(page["pageHandle"])
                break
        if self.page_handle is None:
            create_page = getattr(self.runtime, "create_chat_page", None)
            if create_page is not None:
                self.page_handle = await create_page()
            else:  # compatibility seam for small isolated test runtimes
                result = await self.runtime.bridge.call("create_page")
                self.page_handle = str(result["pageHandle"])
            if not self._claim_page(self.page_handle):
                raise RuntimeError("gpt-auto created a page already owned by another session")
            if not self.provider_session_id and not parse_project_id(self.project_url or ""):
                if hasattr(browser, "page_by_handle"):
                    page = await browser.page_by_handle(self.page_handle)
                    await browser.navigate(page, "https://chatgpt.com/projects")
                    match = await browser.find_project_url(page, self.project_name)
                else:
                    await self.runtime.bridge.call(
                        "navigate", {"pageHandle": self.page_handle, "url": "https://chatgpt.com/projects"}
                    )
                    match = await self.runtime.bridge.call(
                        "find_project_url", {"pageHandle": self.page_handle, "projectName": self.project_name}
                    )
                self.project_url = canonical_project_url(str(match["url"])) + "/project"
                target = self.project_url
            if not target:
                raise RuntimeError("gpt-auto could not resolve a ChatGPT project URL")
            await self.runtime.bridge.call(
                "navigate",
                {
                    "pageHandle": self.page_handle,
                    "url": target,
                    "timeoutMs": int(self.config.chat.navigation_timeout_seconds * 1000),
                },
                timeout=self.config.chat.navigation_timeout_seconds + 2,
            )
        await self._wait_ready()
        snap = await self.snapshot()
        if self.provider_session_id and not url_matches_provider_session(
            snap.url, self.provider_session_id
        ):
            self._move(ChatState.FAILED)
            raise RuntimeError("gpt-auto resumed page has conflicting provider session id")
        self._move(ChatState.READY)

    async def _wait_ready(self) -> None:
        deadline = (
            asyncio.get_running_loop().time() + self.config.chat.ready_timeout_seconds
        )
        while asyncio.get_running_loop().time() < deadline:
            snap = await self.snapshot(allow_recovering=True)
            if snap.composer_present:
                return
            await asyncio.sleep(0.25)
        raise RuntimeError("ChatGPT composer did not become ready")

    async def snapshot(self, *, allow_recovering: bool = False) -> ChatSnapshot:
        if self.state is ChatState.RECOVERING:
            if not allow_recovering:
                try:
                    await asyncio.wait_for(
                        self._recovery_ready.wait(),
                        timeout=self.config.cdp.recovery_timeout_seconds,
                    )
                except TimeoutError as exc:
                    raise RuntimeError("gpt-auto chat recovery timed out") from exc
        if not self.page_handle:
            raise RuntimeError("chat page is not bound")
        page = await self._gpt_browser().page_by_handle(self.page_handle)
        snapshot = ChatSnapshot.from_bridge(await self._gpt_browser().snapshot(
            page, signals=self.config.workflow.bridge_signals()
        ))
        self._last_url = snapshot.url
        self._last_snapshot = snapshot
        return snapshot

    def observed_status(self) -> dict[str, object]:
        """Return sparse page evidence for status projections."""
        if self._last_snapshot is None:
            return {}
        return self._last_snapshot.observe().as_mapping()

    async def acquire_provider_identity(self, initial: ChatSnapshot | None = None) -> ChatSnapshot:
        self._move(ChatState.ACQUIRING_SESSION_ID)
        deadline = (
            asyncio.get_running_loop().time() + self.config.chat.navigation_timeout_seconds
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
                self._move(ChatState.BUSY)
                return snap
            snap = None
            await asyncio.sleep(0.2)
        self._move(ChatState.FAILED)
        raise RuntimeError("ChatGPT accepted the turn but no provider session id appeared")

    async def page_lost(self, handle: str) -> None:
        if handle != self.page_handle or self.state in {ChatState.RECOVERING, ChatState.CLOSED}:
            return
        self.page_handle = None
        self.runtime.release_page(self, handle)
        self._lost_during_turn = self.active_turn_id is not None
        self._move(ChatState.RECOVERING)
        try:
            pages = await self.runtime.bridge.call("list_pages")
            await self.reconcile(pages)
        except BaseException:
            if self.state is ChatState.RECOVERING:
                self._move(ChatState.FAILED)
            raise

    async def retain_after_turn_failure(self, error: BaseException) -> bool:
        """Return to READY when a failed turn left this browser chat usable.

        A turn proof/response failure is not equivalent to browser or session
        destruction.  Keep the durable ChatGPT conversation bound so the
        gateway can resume it, while still using the chat transition engine to
        validate every recovery edge.  Unknown failures remain terminal.
        """
        if not _recoverable_turn_failure(error) or self.state is ChatState.CLOSED:
            return False
        try:
            if self.state is not ChatState.RECOVERING:
                self._move(ChatState.RECOVERING)
            if self.page_handle:
                # The page may still be present after a proof timeout.  Do not
                # navigate away from it: the prompt may already have landed.
                await self._wait_ready()
                self._move(ChatState.READY)
                return True
            if not self.provider_session_id:
                return False
            pages = await self.runtime.bridge.call("list_pages")
            await self.reconcile(pages)
            return self.state is ChatState.READY
        except Exception:  # noqa: BLE001 - failed recovery is terminal below
            if self.state is ChatState.RECOVERING:
                self._move(ChatState.FAILED)
            return False

    def bridge_replaced(self) -> None:
        """Invalidate bridge-local binding before runtime-level recovery."""
        self.page_handle = None
        if self.state is not ChatState.RECOVERING:
            self._move(ChatState.RECOVERING)

    def mark_recovery_failed(self) -> None:
        """Terminalize an isolated recovery failure through the chat graph."""
        if self.state is ChatState.RECOVERING:
            self._move(ChatState.FAILED)

    async def reconcile(self, pages: list[dict]) -> None:
        if self.state is ChatState.CLOSED:
            return
        if self.provider_session_id:
            for page in pages:
                if url_matches_provider_session(
                    str(page.get("url") or ""), self.provider_session_id
                ) and self._claim_page(str(page["pageHandle"])):
                    self.page_handle = str(page["pageHandle"])
                    self._move(ChatState.BUSY if self.active_turn_id else ChatState.READY)
                    return
            self.page_handle = await self._create_recovery_page()
            if not self.runtime.claim_page(self, self.page_handle):
                raise RuntimeError("gpt-auto created a page already owned by another session")
            await self.runtime.bridge.call(
                "navigate",
                {
                    "pageHandle": self.page_handle,
                    "url": self.chat_url,
                    "timeoutMs": int(self.config.chat.navigation_timeout_seconds * 1000),
                },
            )
            await self._wait_ready()
            self._move(ChatState.BUSY if self.active_turn_id else ChatState.READY)
            return
        if self.active_turn_id:
            exact = [page for page in pages if page.get("url") == self._last_url]
            if len(exact) == 1 and self._claim_page(str(exact[0]["pageHandle"])):
                self.page_handle = str(exact[0]["pageHandle"])
                self._move(ChatState.BUSY)
                return
            self._move(ChatState.FAILED)
            return
        self.page_handle = await self._create_recovery_page()
        if not self._claim_page(self.page_handle):
            raise RuntimeError("gpt-auto created a page already owned by another session")
        await self.runtime.bridge.call(
            "navigate",
            {
                "pageHandle": self.page_handle,
                "url": self.project_url,
                "timeoutMs": int(self.config.chat.navigation_timeout_seconds * 1000),
            },
        )
        await self._wait_ready()
        self._move(ChatState.READY)

    async def _create_recovery_page(self) -> str:
        create_page = getattr(self.runtime, "create_chat_page", None)
        if create_page is not None:
            return await create_page()
        result = await self.runtime.bridge.call("create_page")
        return str(result["pageHandle"])

    async def close(self) -> None:
        if self.state is ChatState.CLOSED:
            return
        handle, self.page_handle = self.page_handle, None
        self.runtime.release_page(self, handle)
        self._move(ChatState.CLOSED)
        self.runtime.unregister_chat(self)
        if handle and self.runtime.config.browser.close_tabs_on_session_close:
            try:
                await self.runtime.bridge.call("close_page", {"pageHandle": handle})
            except Exception:
                pass


def _recoverable_turn_failure(error: BaseException) -> bool:
    """Classify only provider turn failures known to preserve the page."""
    return isinstance(error, AudiaGenticError) and error.code in {
        "EXT-GPTAUTO-002",
        "EXT-GPTAUTO-003",
    }
