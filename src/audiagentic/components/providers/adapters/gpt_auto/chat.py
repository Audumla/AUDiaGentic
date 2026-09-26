"""Persistent provider chat with disposable page binding."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from enum import StrEnum

from audiagentic.components.agents.gateway.mapping import normalize_chat_title
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingSink,
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)
from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .config import GptAutoConfig
from .prompt_fingerprint import PromptFingerprint, match_prompt
from .runtime import GptAutoProviderRuntime
from .snapshot import ChatSnapshot
from .urls import (
    canonical_chat_url,
    canonical_project_url,
    parse_project_id,
    parse_provider_session_id,
    url_matches_provider_session,
)

logger = logging.getLogger(__name__)


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
        checkpoint_sink=None,
        provider_session_id: str | None = None,
        chat_url: str | None = None,
        resume_provider_metadata: dict[str, object] | None = None,
        project_key: str | None = None,
    ) -> None:
        self.ag_session_id = ag_session_id
        self.project_name = project_name
        self.project_url = project_url
        # The AUDiaGentic caller's canonical project root -- distinct from
        # project_name (ChatGPT's own project label, often shared across
        # many AUDiaGentic projects that all use the same ChatGPT project).
        # Used only for grouping in the operator dashboard.
        self.project_key = project_key
        self.provider_session_id = provider_session_id
        self.chat_url = chat_url
        self.page_handle: str | None = None
        self.target_id: str | None = None
        self._page_generation = 0
        self._reconciled_binding_token: tuple[object, ...] | None = None
        self.active_turn_id: str | None = None
        # SessionRuntime marks FIFO waiters here before they acquire the
        # provider turn lock. The physical-tab reaper must not reclaim a
        # quiet conversation while a successor request is waiting to use it.
        self.pending_turns = 0
        self.state = ChatState.OPENING
        self.runtime = runtime
        self.config = config
        self.binding_sink = binding_sink
        self.checkpoint_sink = checkpoint_sink
        self._lost_during_turn = False
        self._last_url: str | None = None
        self._last_snapshot: ChatSnapshot | None = None
        # Physical-tab reclamation uses only validated request/session
        # evidence. Raw polling, renderer churn, focus and foreign turns
        # never update this clock; emitted provider activity may.
        self._last_validated_activity_monotonic = time.monotonic()
        self._validated_activity_generation = 0
        metadata = resume_provider_metadata or {}
        self.conversation_title = _metadata_text(metadata, "chat-title")
        self._pending_conversation_title: str | None = None
        self._title_publish_lock = asyncio.Lock()
        self._reconciliation_lock = asyncio.Lock()
        # Every provider page mutation (currently refresh/reload) is
        # serialized against the page binding.  A response watcher and an
        # unresolved-turn reconciler must never navigate the same physical
        # tab concurrently or allow a stale page handle to win.
        self._page_mutation_lock = asyncio.Lock()
        self.unresolved_prompt_message_id = _metadata_text(metadata, "prompt-message-id")
        self.unresolved_assistant_message_id = _metadata_text(metadata, "assistant-message-id")
        self.unresolved_assistant_before_id = _metadata_text(
            metadata, "assistant-before-message-id"
        )
        self.unresolved_prompt_text_digest = _metadata_text(metadata, "prompt-text-digest")
        # Message IDs are durable correlation evidence and remain present
        # after a successful turn.  Only the explicit lifecycle marker says
        # that a previous send still needs reconciliation.
        self.unresolved_turn_pending = _metadata_bool(metadata, "unresolved-turn-pending")
        self._unresolved_match_fingerprint: tuple[object, ...] | None = None
        # GP18 code-review follow-up: the fingerprint match alone proved
        # only that two OBSERVATIONS agreed, not that real TIME passed
        # between them -- a caller retrying admission shortly afterwards
        # could produce a second matching fingerprint almost immediately,
        # unlike _await_response()'s explicit candidate_stability_window
        # wait. Track when the fingerprint was first recorded so clearing
        # requires the same response_stability_seconds gap the main
        # completion path already requires.
        self._unresolved_match_fingerprint_at: float | None = None
        # Keep the last reconciliation decision separate from the durable
        # marker.  The marker says *a turn may still be outstanding*; this
        # evidence says why the latest attempt could not clear it.  It is
        # intentionally ephemeral and is surfaced in the next boundary error.
        self._unresolved_recovery_reason: str | None = None
        self._unresolved_recovery_details: dict[str, object] = {}
        self._reconciliation_refresh_attempted = False
        self._reconciliation_delivery_retry_attempted = False
        self._defer_unresolved_reconciliation = False
        self._checkpoint_metadata: dict[str, object] = {
            key: metadata[key]
            for key in (
                "recovery-state",
                "unresolved-turn-id",
                "unresolved-baseline-user-id",
                "unresolved-baseline-assistant-id",
                "unresolved-baseline-user-count",
                "unresolved-baseline-assistant-count",
            )
            if key in metadata and metadata[key] not in (None, "")
        }
        self._recovery_ready = asyncio.Event()
        self._recovery_ready.set()

    async def persist_unresolved_checkpoint(
        self,
        *,
        turn_id: str,
        baseline: ChatSnapshot | None,
    ) -> None:
        """Write the side-effect checkpoint before browser Send is invoked."""
        self._reconciliation_delivery_retry_attempted = False
        self._checkpoint_metadata = {
            "recovery-state": "side-effect-may-have-started",
            "unresolved-turn-id": turn_id,
        }
        if baseline is not None:
            for key, value in (
                ("unresolved-baseline-user-id", baseline.latest_user_id),
                ("unresolved-baseline-assistant-id", baseline.latest_assistant_id),
                ("unresolved-baseline-user-count", baseline.user_count),
                ("unresolved-baseline-assistant-count", baseline.assistant_count),
            ):
                if value is not None and value != "":
                    self._checkpoint_metadata[key] = value
        sink = self.checkpoint_sink
        if sink is None:
            return
        result = sink({**self.unresolved_metadata(), **self._checkpoint_metadata})
        if asyncio.iscoroutine(result):
            await result

    async def persist_unresolved_identity(self) -> None:
        """Persist prompt identity without rewriting the pre-send baseline."""
        sink = self.checkpoint_sink
        if sink is None:
            return
        result = sink(self.unresolved_metadata())
        if inspect.isawaitable(result):
            await result

    async def persist_unresolved_clear(self) -> None:
        """Durably clear the checkpoint only after terminal proof."""
        sink = self.checkpoint_sink
        if sink is None:
            self._checkpoint_metadata = {}
            return
        # Emit the intended durable state explicitly.  Callers may persist
        # before mutating the in-memory marker so a failed write cannot expose
        # READY and then resurrect an unresolved lock after restart.
        result = sink({"unresolved-turn-pending": False})
        if inspect.isawaitable(result):
            await result
        self._checkpoint_metadata = {}

    def _claim_page(self, page_handle: str) -> bool:
        """Claim a page when the runtime exposes ownership tracking.

        The fallback keeps small adapter test doubles compatible while the
        production runtime always supplies the exclusive ownership method.
        """
        claim = getattr(self.runtime, "claim_page", None)
        return True if claim is None else bool(claim(self, page_handle))

    def _move(self, target: ChatState) -> None:
        # CDP target events and an admission call can observe the same loss at
        # the same time.  The state transition itself is idempotent so the
        # second observer cannot turn a successfully completed recovery into
        # an illegal ``ready -> ready`` failure.
        if self.state is target:
            return
        failure = _CHAT_ENGINE.check(self.state.value, target.value)
        if failure:
            raise RuntimeError(
                f"illegal gpt-auto chat transition {self.state}->{target}: {failure}"
            )
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
            # The dashboard tab is the durable owner/anchor for the managed
            # GPT window. New sessions become tabs in that existing window;
            # only the first session creates the anchor window. This keeps
            # all GPT projects in one discoverable browser window and lets a
            # later gateway process recover it from the dashboard URL.
            anchor_page = None
            if self.config.browser.dedicated_window:
                resolve_anchor = getattr(self.runtime, "dedicated_window_anchor_page", None)
                if resolve_anchor is not None:
                    anchor_page = await resolve_anchor()
            result = await composite_open(
                project_name=self.project_name,
                project_url=self.project_url,
                anchor_page=anchor_page,
                navigation_timeout=self.config.chat.navigation_timeout_seconds,
                ready_timeout=self.config.chat.ready_timeout_seconds,
            )
            self.page_handle = result["page"].handle
            target_id = str(getattr(result["page"], "target_id", "") or "")
            if target_id:
                self.target_id = target_id
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
        target = self.chat_url if self.provider_session_id else self.project_url
        if self.provider_session_id:
            claim_conversation = getattr(self.runtime, "claim_conversation", None)
            if claim_conversation is not None and not claim_conversation(
                self, self.provider_session_id
            ):
                raise RuntimeError("gpt-auto provider conversation is already owned")
            find_page = getattr(self.runtime, "find_conversation_page", None)
            page = (
                await find_page(
                    self.provider_session_id,
                    preferred_target_id=self.target_id,
                )
                if find_page is not None
                else None
            )
            if page is not None:
                if not self._claim_page(str(page["pageHandle"])):
                    raise RuntimeError("gpt-auto retained conversation page is already owned")
                self._bind_page(page)
                await self._prefer_active_conversation_page()
            elif not target:
                # provider_session_id is set but neither a retained browser
                # tab nor a durable chat-url is available. Creating a fresh
                # page here would have nothing to navigate to and nothing to
                # bind it to -- since tabs are retained rather than closed by
                # default, that page would be silently orphaned. Fail before
                # claiming a page instead of after.
                self._move(ChatState.FAILED)
                raise RuntimeError(
                    "gpt-auto resume requires a retained browser tab or a durable "
                    "chat-url; neither is available"
                )
        if self.page_handle is None:
            create_page = getattr(self.runtime, "create_chat_page", None)
            if create_page is not None:
                self.page_handle = await create_page()
            else:  # compatibility seam for small isolated test runtimes
                result = await self.runtime.bridge.call("create_page")
                self.page_handle = str(result["pageHandle"])
            if not self._claim_page(self.page_handle):
                raise RuntimeError("gpt-auto created a page already owned by another session")
            page_record = getattr(self.runtime, "page_record", None)
            if page_record is not None:
                record = await page_record(self.page_handle)
                if record is not None:
                    self._bind_page(record)
            if not self.provider_session_id and not parse_project_id(self.project_url or ""):
                if hasattr(browser, "page_by_handle"):
                    page = await browser.page_by_handle(self.page_handle)
                    await browser.navigate(page, "https://chatgpt.com/")
                    match = await browser.find_project_url(page, self.project_name)
                else:
                    await self.runtime.bridge.call(
                        "navigate",
                        {"pageHandle": self.page_handle, "url": "https://chatgpt.com/"},
                    )
                    match = await self.runtime.bridge.call(
                        "find_project_url",
                        {"pageHandle": self.page_handle, "projectName": self.project_name},
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
        # _wait_ready() already tolerates RECOVERING (it calls
        # wait_quiescent(allow_recovering=True)) -- a shared-bridge
        # replacement can race this exact resume window and move state to
        # RECOVERING between that call and this one. Without allow_recovering
        # here too, this would block for the full recovery-timeout waiting on
        # a signal nothing in this flow ever sets, before eventually failing
        # anyway -- a needless hang on the way to the same outcome.
        snap = await self.snapshot(allow_recovering=True)
        if self.provider_session_id and not url_matches_provider_session(
            snap.url, self.provider_session_id
        ):
            self._move(ChatState.FAILED)
            raise RuntimeError("gpt-auto resumed page has conflicting provider session id")
        if (
            self.provider_session_id
            and self.unresolved_turn_pending
            and not self._defer_unresolved_reconciliation
        ):
            # A resumed conversation with an unresolved Send is not ordinary
            # READY.  Keep admission closed until the exact prompt/response
            # outcome is reconciled (or leave it RECOVERING for lazy retry).
            self._move(ChatState.RECOVERING)
            reconciled = await self._await_unresolved_reconciliation()
            if self.unresolved_turn_pending:
                return
            if reconciled and not await self._reconciled_binding_is_current():
                return
        self._move(ChatState.READY)

    def defer_unresolved_reconciliation(self) -> None:
        """Leave the checkpoint for the request-owned recovery turn.

        Gateway restart recovery must first reattach the exact conversation.
        The request-owned ``resume_existing`` turn is the only authority that
        may observe, persist the response artifact, and clear this checkpoint.
        """
        self._defer_unresolved_reconciliation = True

    def _bind_page(self, page: dict) -> None:
        page_handle = str(page["pageHandle"])
        target_id = str(page.get("targetId") or "")
        if page_handle != self.page_handle or (target_id and target_id != self.target_id):
            self._page_generation += 1
        self.page_handle = page_handle
        if target_id:
            self.target_id = target_id

    async def ensure_ready(self) -> None:
        """Lazily recover admission and only expose READY after quiescence."""
        # Bridge page handles are local to one CDP connection and can be
        # invalidated without the runtime seeing a Target event (for example,
        # an operator closes a tab through a second CDP client).  A handle can
        # even be recycled for an unrelated tab.  Validate the binding before
        # admitting a turn so the turn never fails with an opaque
        # ``unknown-or-closed-page`` error; recovery then rebinds by stable
        # target/provider URL and, if necessary, recreates the conversation tab.
        await self._validate_page_binding()
        if self.provider_session_id and not self.page_handle:
            # AS125 may have reclaimed only the physical tab. Reopen the
            # exact retained provider conversation before admitting a turn;
            # never fall through to a fresh ChatGPT conversation.
            self._move(ChatState.RECOVERING)
            pages = await self.runtime.bridge.call("list_pages")
            await self.reconcile(pages)
        if self.state is ChatState.RECOVERING:
            if self.page_handle and self.unresolved_turn_pending:
                if await self._await_unresolved_reconciliation():
                    if (
                        self.state is ChatState.RECOVERING
                        and await self._reconciled_binding_is_current()
                    ):
                        self._move(ChatState.READY)
            else:
                pages = await self.runtime.bridge.call("list_pages")
                await self.reconcile(pages)
                if self.state is ChatState.RECOVERING and self.unresolved_turn_pending:
                    if await self._await_unresolved_reconciliation():
                        if (
                            self.state is ChatState.RECOVERING
                            and await self._reconciled_binding_is_current()
                        ):
                            self._move(ChatState.READY)
        if self.state is not ChatState.READY:
            if self._unresolved_recovery_reason == "provider-conversation-not-found":
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-005",
                    kind="providers",
                    message=(
                        "gpt-auto could not find the durable ChatGPT conversation; "
                        "it may have been deleted. The session is closed and will "
                        "not reopen that conversation automatically."
                    ),
                    details={
                        "failure-reason": "provider-conversation-not-found",
                        "provider-session-id": self.provider_session_id,
                        **self._unresolved_recovery_diagnostics(),
                    },
                )
            if self.state is ChatState.RECOVERING and self.unresolved_turn_pending:
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-004",
                    kind="providers",
                    message=(
                        "gpt-auto could not reconcile the previous turn; "
                        "this admission attempt did not submit a new prompt, but the "
                        "prior unresolved turn's outcome is not yet proven -- it may "
                        "already have been sent and may even have completed"
                    ),
                    details={
                        "failure-reason": "unresolved-turn-not-reconciled",
                        "state": self.state.value,
                        "prompt-id-available": bool(self.unresolved_prompt_message_id),
                        "prompt-text-digest-available": bool(self.unresolved_prompt_text_digest),
                        "suggestion": "resume the same session after the provider is idle, or resubmit only after confirming the prompt is absent",
                        **self._unresolved_recovery_diagnostics(),
                        **_unresolved_observation_details(self._last_snapshot),
                    },
                )
            raise RuntimeError(f"gpt-auto chat is not ready (state={self.state.value})")

    def mark_validated_activity(self, at: float | None = None) -> None:
        """Renew physical-tab retention from request-owned validated evidence."""
        self._last_validated_activity_monotonic = (
            time.monotonic() if at is None else float(at)
        )
        self._validated_activity_generation += 1

    def mark_turn_pending(self) -> None:
        """Expose a queued session turn to the physical-tab reaper."""
        self.pending_turns += 1

    def clear_turn_pending(self) -> None:
        """Remove one queued session turn from the reaper's protection set."""
        self.pending_turns = max(0, self.pending_turns - 1)

    async def close_physical_page_if_idle(
        self,
        *,
        now: float,
        idle_timeout_seconds: float,
    ) -> bool:
        """Close only an idle physical tab, preserving logical session state."""
        if idle_timeout_seconds <= 0:
            return False
        async with self._page_mutation_lock:
            handle = self.page_handle
            generation = self._validated_activity_generation
            if (
                self.active_turn_id is not None
                or self.pending_turns > 0
                or not handle
                or now - self._last_validated_activity_monotonic < idle_timeout_seconds
            ):
                return False
            try:
                await self.runtime.bridge.call("close_page", {"pageHandle": handle})
            except Exception:
                logger.debug(
                    "gpt-auto physical idle-tab close failed",
                    extra={"session-id": self.ag_session_id, "page-handle": handle},
                    exc_info=True,
                )
                return False
            if (
                handle != self.page_handle
                or generation != self._validated_activity_generation
                or self.active_turn_id is not None
                or self.pending_turns > 0
            ):
                return False
            self.page_handle = None
            self.target_id = None
            self._page_generation += 1
            self.runtime.release_page(self, handle)
            logger.info(
                "gpt-auto reclaimed idle physical tab",
                extra={"session-id": self.ag_session_id},
            )
            return True

    async def _await_unresolved_reconciliation(self) -> bool:
        """Observe one unresolved turn through the configured readiness bound.

        Reconciliation requires a stability interval by design.  Calling the
        single-observation primitive once and immediately rejecting admission
        makes that interval impossible to satisfy in one queued successor.
        Keep the prompt admission closed, but continue read-only observations
        until the previous turn is proven terminal or the existing bounded
        readiness window expires.  This never submits or resubmits a prompt.
        """
        async with self._reconciliation_lock:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.config.chat.ready_timeout_seconds
            retryable = {
                "awaiting-second-stable-observation",
                "provider-not-quiescent",
            }
            while self.unresolved_turn_pending:
                try:
                    async with asyncio.timeout_at(deadline):
                        if await self._reconcile_unresolved_turn():
                            return True
                except TimeoutError:
                    self._set_unresolved_recovery("reconciliation-readiness-timeout")
                    return not self.unresolved_turn_pending
                if self._unresolved_recovery_reason not in retryable:
                    return False
                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._set_unresolved_recovery("reconciliation-readiness-timeout")
                    return False
                await asyncio.sleep(min(self.config.turn.poll_interval_seconds, remaining))
            return True

    def _binding_token(self, snapshot: ChatSnapshot) -> tuple[object, ...]:
        return (
            self._page_generation,
            self.page_handle,
            self.target_id,
            self.provider_session_id,
            canonical_chat_url(snapshot.url),
        )

    async def _binding_token_is_current(self, token: tuple[object, ...]) -> bool:
        generation, handle, target_id, provider_session_id, chat_url = token
        if (
            generation != self._page_generation
            or not handle
            or handle != self.page_handle
            or target_id != self.target_id
            or provider_session_id != self.provider_session_id
        ):
            return False
        try:
            page = await self._gpt_browser().page_by_handle(str(handle))
        except Exception:
            return False
        current_target = str(getattr(page, "target_id", "") or "")
        current_url = str(getattr(page, "url", "") or "")
        if not current_url:
            try:
                observed = ChatSnapshot.from_bridge(
                    await self._gpt_browser().snapshot(
                        page,
                        signals=self.config.workflow.bridge_signals(),
                    )
                )
                current_url = observed.url
            except Exception:
                return False
        same_conversation = (
            url_matches_provider_session(current_url, str(provider_session_id))
            if provider_session_id
            else bool(chat_url and canonical_chat_url(current_url) == chat_url)
        )
        return bool(
            (not target_id or not current_target or current_target == target_id)
            and same_conversation
            and canonical_chat_url(current_url) == chat_url
        )

    async def _reconciled_binding_is_current(self) -> bool:
        token = self._reconciled_binding_token
        if token is None:
            return bool(self.page_handle)
        if await self._binding_token_is_current(token):
            return True
        self._set_unresolved_recovery("page-binding-changed-after-reconciliation")
        return False

    async def _validate_page_binding(self) -> None:
        """Detect an externally closed or recycled page handle and recover it."""
        if not self.page_handle or self.state in {ChatState.CLOSED, ChatState.FAILED}:
            return
        browser = self._gpt_browser()
        handle = self.page_handle
        try:
            page = await browser.page_by_handle(handle)
        except Exception:
            page = None
        if page is not None:
            current_target = str(getattr(page, "target_id", "") or "")
            current_url = str(getattr(page, "url", "") or "")
            recycled = bool(self.target_id and current_target and current_target != self.target_id)
            wrong_conversation = bool(
                self.provider_session_id
                and current_url
                and not url_matches_provider_session(current_url, self.provider_session_id)
            )
            if not recycled and not wrong_conversation:
                return
        self.page_handle = None
        self.runtime.release_page(self, handle)
        if self.state is not ChatState.RECOVERING:
            self._move(ChatState.RECOVERING)
        pages = await self.runtime.bridge.call("list_pages")
        await self.reconcile(pages if isinstance(pages, list) else [])

    async def _wait_ready(self) -> None:
        await self.wait_quiescent(allow_recovering=True)

    async def wait_quiescent(self, *, allow_recovering: bool = False) -> ChatSnapshot:
        """Prove the provider conversation is idle across two observations.

        A composer can remain mounted while ChatGPT is generating.  Admission,
        recovery, and cancellation therefore share this stronger boundary.
        """
        deadline = asyncio.get_running_loop().time() + self.config.chat.ready_timeout_seconds
        stable = 0
        last: ChatSnapshot | None = None
        while asyncio.get_running_loop().time() < deadline:
            snap = await self.snapshot(allow_recovering=allow_recovering)
            if provider_quiescent(snap):
                stable = stable + 1 if last is not None and _same_quiescent_state(last, snap) else 1
                if stable >= 2:
                    return snap
            else:
                stable = 0
            last = snap
            await asyncio.sleep(0.25)
        raise RuntimeError("ChatGPT conversation did not become quiescent")

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
        target_id = str(getattr(page, "target_id", "") or "")
        if target_id:
            self.target_id = target_id
        snapshot = ChatSnapshot.from_bridge(
            await self._gpt_browser().snapshot(page, signals=self.config.workflow.bridge_signals())
        )
        self._last_url = snapshot.url
        self._last_snapshot = snapshot
        # Capture labels during recovery/baseline observations too, not only
        # the normal response loop. Never relay a label from a different tab.
        if snapshot.conversation_title and (
            not self.provider_session_id
            or url_matches_provider_session(snapshot.url, self.provider_session_id)
        ):
            try:
                await self.publish_conversation_title(snapshot.conversation_title)
            except Exception:
                logger.debug("gpt-auto title persistence failed; will retry on next observation", exc_info=True)
        return snapshot

    async def materialize_latest_assistant_turn(self) -> bool:
        """Mount the latest turn's completion controls when ChatGPT virtualizes it.

        This is intentionally a narrow observation aid used by the response
        watcher.  It does not refresh the page, submit a prompt, or change
        provider/session ownership.  Small test doubles may not expose the
        provider-specific method; in that case the safe answer is ``False``
        and normal evidence/timeout handling remains unchanged.
        """
        if not self.page_handle:
            return False
        browser = self._gpt_browser()
        materialize = getattr(browser, "materialize_latest_assistant_turn", None)
        if not callable(materialize):
            return False
        page = await browser.page_by_handle(self.page_handle)
        return bool(await materialize(page))

    async def retry_delivery_timeout(self) -> bool:
        """Activate one provider-owned delivery Retry control; never resubmit."""
        if not self.page_handle:
            return False
        browser = self._gpt_browser()
        retry = getattr(browser, "retry_delivery_timeout", None)
        if not callable(retry):
            return False
        page = await browser.page_by_handle(self.page_handle)
        return bool(await retry(page))

    async def release_focus_emulation(self) -> None:
        """Release provider focus emulation after the watcher snapshots."""
        if not self.page_handle:
            return
        browser = self._gpt_browser()
        release = getattr(browser, "release_focus_emulation", None)
        if not callable(release):
            return
        page = await browser.page_by_handle(self.page_handle)
        await release(page)

    async def _reconcile_unresolved_turn(self) -> bool:
        """Prove the retained prompt reached a terminal provider outcome."""
        if not self.unresolved_turn_pending:
            return True
        observed_page_generation = self._page_generation
        try:
            snapshot = await self.snapshot(allow_recovering=True)
        except Exception as exc:  # noqa: BLE001 - preserve diagnostic context
            self._reset_unresolved_match_candidate()
            self._set_unresolved_recovery(
                "snapshot-observation-failed",
                exception_type=type(exc).__name__,
                exception=str(exc),
            )
            return False
        # A provider-side delivery timeout can leave the durable turn marked
        # unresolved even though the conversation is still recoverable. Use
        # the exact Retry control once, without resubmitting the prompt, then
        # re-read the same conversation before applying failure evidence.
        completion_candidate = _reconciliation_completion_candidate(self, snapshot)
        # Authentication is a hard veto and must never be followed by a
        # provider-side click, even when a stale Retry control is visible.
        if "auth-required" in snapshot.dom_signals:
            self._set_unresolved_recovery("authentication-required")
            return False
        if (
            "delivery-timeout-retry" in snapshot.dom_signals
            and not self._reconciliation_delivery_retry_attempted
            and not completion_candidate
        ):
            _, prompt_reason, _ = _unresolved_prompt_match_diagnostics(self, snapshot)
            # Retry is a page-global side effect.  A digest match in an older
            # user turn is sufficient to correlate a read-only terminal
            # witness, but it is not sufficient to click Retry: only the
            # latest visible user turn may own that control.
            latest_digest = (
                PromptFingerprint.from_text(snapshot.latest_user_text).digest
                if snapshot.latest_user_text
                else None
            )
            retry_is_request_owned = (
                prompt_reason == "prompt-id-match"
                or (
                    prompt_reason in {
                        "prompt-text-digest-match",
                        "prompt-id-mismatch-text-digest-match",
                    }
                    and latest_digest == self.unresolved_prompt_text_digest
                )
            )
            if retry_is_request_owned:
                self._reconciliation_delivery_retry_attempted = True
                try:
                    if await self.retry_delivery_timeout():
                        await asyncio.sleep(self.config.turn.poll_interval_seconds)
                        snapshot = await self.snapshot(allow_recovering=True)
                except Exception as exc:  # noqa: BLE001 - preserve recovery evidence
                    self._set_unresolved_recovery(
                        "delivery-timeout-retry-failed",
                        exception_type=type(exc).__name__,
                        exception=str(exc),
                    )
                    return False
            else:
                self._set_unresolved_recovery(
                    "delivery-timeout-retry-not-request-owned",
                    observed_prompt_reason=prompt_reason,
                )
                return False
        # A retained CDP page can have a stale React/DOM snapshot even though
        # the provider conversation has already completed. One same-URL
        # refresh is a read-only reconciliation attempt; it never resends the
        # prompt and is bounded to once per unresolved turn.
        if (
            not snapshot.generating
            and (
                not _reconciliation_evidence_clear(snapshot)
                or not snapshot.latest_assistant_id
                or not snapshot.latest_assistant_text
            )
            and await self._refresh_for_reconciliation()
        ):
            try:
                snapshot = await self.snapshot(allow_recovering=True)
            except Exception as exc:  # noqa: BLE001 - preserve diagnostic context
                self._set_unresolved_recovery(
                    "refresh-observation-failed",
                    exception_type=type(exc).__name__,
                    exception=str(exc),
                )
                return False
        if snapshot.generating:
            logger.warning(
                "gpt-auto Tier-3 generating signal disagreed with reconciliation "
                "evidence during unresolved-turn recovery, dom_signals=%s",
                sorted(snapshot.dom_signals),
            )
        if not _reconciliation_evidence_clear(
            snapshot, allow_terminal_errors=completion_candidate
        ):
            self._reset_unresolved_match_candidate()
            self._set_unresolved_recovery(
                "provider-not-quiescent",
                composer_present=snapshot.composer_present,
                composer_editable=snapshot.composer_editable,
                error_present=snapshot.error_present,
                dom_signals=sorted(snapshot.dom_signals),
            )
            return False
        assistant_id = snapshot.latest_assistant_id
        if not assistant_id:
            self._reset_unresolved_match_candidate()
            self._set_unresolved_recovery("assistant-response-id-not-observed")
            return False
        if not snapshot.latest_assistant_text:
            # Background ChatGPT tabs can retain the terminal message identity
            # and controls while virtualizing the response body.  The normal
            # response watcher already materializes that final turn before it
            # decides text is unavailable; unresolved-turn recovery must use
            # the same observation seam.  Otherwise a cancelled/lost watcher
            # poisons an otherwise healthy persistent conversation and every
            # queued successor is rejected even though ChatGPT completed.
            materialized = False
            try:
                materialized = await self.materialize_latest_assistant_turn()
                if materialized:
                    snapshot = await self.snapshot(allow_recovering=True)
                    assistant_id = snapshot.latest_assistant_id
            except Exception as exc:  # noqa: BLE001 - retain recovery evidence
                self._set_unresolved_recovery(
                    "assistant-response-materialization-failed",
                    exception_type=type(exc).__name__,
                    exception=str(exc),
                )
                return False
            finally:
                if materialized:
                    try:
                        await self.release_focus_emulation()
                    except Exception:  # noqa: BLE001 - focus release is best-effort
                        logger.debug(
                            "gpt-auto unresolved reconciliation focus release failed",
                            exc_info=True,
                        )
            if not assistant_id:
                self._reset_unresolved_match_candidate()
                self._set_unresolved_recovery("assistant-response-id-not-observed")
                return False
            # Text recovery and admission safety are separate decisions.  A
            # stable, quiescent, newer assistant identity proves the provider
            # turn ended even when ChatGPT keeps its body virtualized.  Carry
            # on to correlation/terminal proof; the missing body is recorded
            # when that proof succeeds rather than poisoning the session.
        prompt_match, prompt_reason, prompt_details = _unresolved_prompt_match_diagnostics(
            self, snapshot
        )
        if prompt_match is None:
            # A newer assistant than the baseline is not request correlation:
            # a person or another controller may have inserted an intervening
            # turn.  The only safe fallback when the user node is virtualized
            # is the request-owned assistant identity captured by the watcher.
            expected_assistant_id = self.unresolved_assistant_message_id
            if expected_assistant_id and assistant_id == expected_assistant_id:
                prompt_match = f"assistant-id:{assistant_id}"
                prompt_reason = "request-owned-assistant-id"
                prompt_details = {
                    **prompt_details,
                    "observed-assistant-id": assistant_id,
                    "correlation-fallback": "request-owned-assistant-id",
                }
            else:
                self._reset_unresolved_match_candidate()
                self._set_unresolved_recovery(prompt_reason, **prompt_details)
                return False
        # A stable partial assistant message can look idle while ChatGPT is
        # still stalled in a tool-backed turn.  Require explicit terminal
        # evidence before clearing the unresolved marker; the caller receives
        # a structured recovery error when that evidence never appears.
        #
        # GP18 code review: this used to accept ANY single witness
        # (completion-control alone, or one canvas control alone) via a
        # flat .intersection() -- weaker than response-complete's own gate,
        # which requires a WHOLE corroborating pair together (GP17: a
        # single witness is proven to fire on genuinely-incomplete turns).
        # Reuses the SAME any-of-groups the real completion gate uses
        # (config.workflow.policy("response-complete").any_of_groups)
        # instead of a separately-maintained witness set, so recovery and
        # normal completion can never drift into different terminal
        # semantics again.
        completion_groups = self.config.workflow.policy("response-complete").any_of_groups
        # not-generating is a derived fact (from snapshot.generating), not
        # a DOM signal -- it never appears in dom_signals itself, so it
        # must be added explicitly to match what the group actually
        # requires (mirrors turn.py's _facts()).
        true_facts = snapshot.dom_signals | ({"not-generating"} if not snapshot.generating else set())
        # Code review (2026-08-17): EvidencePolicy.evaluate() treats an
        # absent/empty any-of-groups section as no any-of requirement at
        # all, but any(...) over an empty sequence is False -- a valid
        # overlay that legally removes any-of-groups from response-complete
        # would silently make unresolved-turn recovery impossible here.
        # Match EvidencePolicy's own semantics explicitly.
        groups_satisfied = not completion_groups or any(
            group <= true_facts for group in completion_groups
        )
        if not groups_satisfied:
            self._reset_unresolved_match_candidate()
            self._set_unresolved_recovery(
                "completion-evidence-missing",
                required_signal="-or-".join("+".join(sorted(group)) for group in completion_groups),
                observed_dom_signals=sorted(snapshot.dom_signals),
            )
            return False
        if prompt_reason == "request-owned-assistant-id":
            terminal = True
        elif self.unresolved_assistant_message_id:
            terminal = assistant_id == self.unresolved_assistant_message_id
            # A provider-side Retry can replace the assistant node with a
            # fresh ID while keeping the original user prompt as the latest
            # turn. If prompt ID correlation is exact, user count is
            # unchanged, and the new assistant is newer than the durable
            # pre-turn node, this is the same turn—not an intervening chat.
            if (
                not terminal
                and prompt_reason == "prompt-id-match"
                and snapshot.latest_user_id == self.unresolved_prompt_message_id
                and snapshot.user_count
                == int(
                    self._checkpoint_metadata.get(
                        "unresolved-baseline-user-count", snapshot.user_count
                    )
                )
                and assistant_id != self.unresolved_assistant_before_id
            ):
                terminal = True
                prompt_reason = "prompt-id-match-retried-assistant"
        else:
            terminal = assistant_id != self.unresolved_assistant_before_id
        if not terminal:
            self._reset_unresolved_match_candidate()
            self._set_unresolved_recovery(
                "assistant-response-not-terminal-match",
                observed_assistant_id=assistant_id,
                expected_assistant_id=self.unresolved_assistant_message_id,
                assistant_before_id=self.unresolved_assistant_before_id,
            )
            return False
        response_text_available = bool(snapshot.latest_assistant_text)
        terminal_evidence = tuple(sorted(snapshot.dom_signals))
        match_fingerprint = (
            self.provider_session_id,
            observed_page_generation,
            self.target_id,
            snapshot.url,
            prompt_match,
            prompt_reason,
            assistant_id,
            response_text_available,
            (
                PromptFingerprint.from_text(snapshot.latest_assistant_text).digest
                if response_text_available
                else None
            ),
            terminal_evidence,
            snapshot.generating,
        )
        now = time.monotonic()
        if self._unresolved_match_fingerprint != match_fingerprint:
            self._unresolved_match_fingerprint = match_fingerprint
            self._unresolved_match_fingerprint_at = now
            self._set_unresolved_recovery(
                "awaiting-second-stable-observation",
                correlation=prompt_match,
                assistant_id=assistant_id,
            )
            return False
        # GP18 code review: a matching fingerprint alone only proves two
        # OBSERVATIONS agreed -- not that any real time passed between
        # them. A caller retrying admission shortly afterwards could
        # reconcile against a canvas turn's premature witnesses (GP34)
        # almost immediately. Require the same response_stability_seconds
        # gap _await_response()'s own candidate window enforces.
        # Do not use ``or now`` here: deterministic clocks and some test/live
        # harnesses legitimately start at monotonic time 0.0.  ``None`` is
        # the only value that means the stability clock was never armed.
        elapsed = (
            0.0
            if self._unresolved_match_fingerprint_at is None
            else now - self._unresolved_match_fingerprint_at
        )
        required_stability = (
            self.config.turn.response_generating_override_stability_seconds
            if snapshot.generating
            else self.config.turn.response_stability_seconds
        )
        if elapsed < required_stability:
            self._set_unresolved_recovery(
                "awaiting-second-stable-observation",
                correlation=prompt_match,
                assistant_id=assistant_id,
                elapsed_seconds=round(elapsed, 3),
                required_stability_seconds=required_stability,
            )
            return False
        if self._page_generation != observed_page_generation or not self.page_handle:
            self._reset_unresolved_match_candidate()
            self._set_unresolved_recovery("page-binding-changed-during-reconciliation")
            return False
        binding_token = self._binding_token(snapshot)
        if self.provider_session_id and not await self._binding_token_is_current(binding_token):
            self._reset_unresolved_match_candidate()
            self._set_unresolved_recovery("provider-conversation-changed-during-reconciliation")
            return False
        # Commit the safety fence before exposing the in-memory session as
        # ready. A failed durable write leaves the unresolved marker intact.
        await self.persist_unresolved_clear()
        self.clear_unresolved_turn()
        self._reconciled_binding_token = binding_token
        if not response_text_available and self.provider_session_id:
            # Diagnostic metadata is after the authoritative clear and has a
            # separate small bound, so it cannot retain a healthy session.
            try:
                async with asyncio.timeout(
                    min(1.0, max(0.05, self.config.turn.poll_interval_seconds))
                ):
                    result = self.binding_sink(
                        ProviderSessionBindingUpdate(
                            provider_session_ref=ProviderSessionRef(self.provider_session_id),
                            metadata={
                                "reconciliation-warning": "prior-response-text-unavailable",
                                "reconciled-assistant-message-id": assistant_id,
                            },
                        )
                    )
                    if inspect.isawaitable(result):
                        await result
            except Exception:  # noqa: BLE001 - warning must not hold the provider lock
                logger.warning(
                    "gpt-auto could not persist reconciliation warning",
                    extra={"session-id": self.ag_session_id},
                    exc_info=True,
                )
        return True

    def _set_unresolved_recovery(self, reason: str, **details: object) -> None:
        self._unresolved_recovery_reason = reason
        self._unresolved_recovery_details = {
            key.replace("_", "-"): value
            for key, value in details.items()
            if value is not None and value != "" and value != []
        }

    def _unresolved_recovery_diagnostics(self) -> dict[str, object]:
        values: dict[str, object] = {}
        if self._unresolved_recovery_reason:
            values["recovery-reason"] = self._unresolved_recovery_reason
        if self._unresolved_recovery_details:
            values["recovery-details"] = dict(self._unresolved_recovery_details)
        return values

    def unresolved_metadata(self) -> dict[str, object]:
        """Return sparse correlation evidence for successor session records."""
        values: dict[str, object] = {
            "unresolved-turn-pending": self.unresolved_turn_pending,
        }
        for key, value in (
            ("prompt-message-id", self.unresolved_prompt_message_id),
            ("assistant-message-id", self.unresolved_assistant_message_id),
            ("assistant-before-message-id", self.unresolved_assistant_before_id),
            ("prompt-text-digest", self.unresolved_prompt_text_digest),
        ):
            if value:
                values[key] = value
        values.update(self._checkpoint_metadata)
        return values

    def mark_submission_unresolved(self, prompt_text: str | None = None) -> None:
        """Record that a send command completed but its provider identity is unknown."""
        self.unresolved_turn_pending = True
        self._unresolved_recovery_reason = None
        self._unresolved_recovery_details = {}
        self._reconciliation_refresh_attempted = False
        if prompt_text:
            self.unresolved_prompt_text_digest = PromptFingerprint.from_text(prompt_text).digest

    def mark_prompt_submitted(
        self,
        prompt_id: str,
        assistant_before_id: str | None,
        prompt_text: str | None = None,
    ) -> None:
        self.unresolved_turn_pending = True
        self._unresolved_recovery_reason = None
        self._unresolved_recovery_details = {}
        self._reconciliation_refresh_attempted = False
        self.unresolved_prompt_message_id = prompt_id
        self.unresolved_assistant_before_id = assistant_before_id
        if prompt_text:
            self.unresolved_prompt_text_digest = PromptFingerprint.from_text(prompt_text).digest

    def mark_assistant_observed(self, assistant_id: str) -> None:
        self.unresolved_assistant_message_id = assistant_id

    def _reset_unresolved_match_candidate(self) -> None:
        """Discard any in-progress stability timer for unresolved-turn
        recovery (GP38/GP40 code review, 2026-08-17): the elapsed-time
        check only proves two matching observations were seen at least
        response_stability_seconds apart, not that the terminal candidate
        was continuously eligible in between. Without this reset, a
        candidate armed by one terminal observation could survive an
        intervening non-terminal one (generation resuming, evidence
        temporarily unclear) and later be revived by an unrelated brief
        flicker, satisfying "two matches N seconds apart" without ever
        observing N continuous seconds of real stability."""
        self._unresolved_match_fingerprint = None
        self._unresolved_match_fingerprint_at = None

    def clear_unresolved_turn(self) -> None:
        self.unresolved_turn_pending = False
        self.unresolved_prompt_message_id = None
        self.unresolved_assistant_message_id = None
        self.unresolved_assistant_before_id = None
        self.unresolved_prompt_text_digest = None
        self._unresolved_match_fingerprint = None
        self._unresolved_match_fingerprint_at = None
        self._unresolved_recovery_reason = None
        self._unresolved_recovery_details = {}

    async def refresh_bound_conversation(
        self,
        *,
        request_id: str | None = None,
        expected_binding: tuple[object, ...] | None = None,
        trigger: str = "response-recovery",
    ) -> bool:
        """Refresh only the currently bound provider conversation page.

        This is deliberately a page-local recovery primitive.  It never
        calls readiness/open/rebind, creates a page, creates a provider
        session, or submits a prompt.  The binding and page-generation checks
        turn a concurrent close/rebind into a failed recovery attempt rather
        than allowing navigation of an unrelated tab.
        """
        async with self._page_mutation_lock:
            handle = self.page_handle
            bound_url = canonical_chat_url(self.chat_url)
            if not handle or not self.provider_session_id or not bound_url:
                self._set_unresolved_recovery(
                    "refresh-missing-page-binding",
                    request_id=request_id,
                    trigger=trigger,
                )
                return False
            token = expected_binding
            if token is None and self._last_snapshot is not None:
                token = self._binding_token(self._last_snapshot)
            if token is not None and not await self._binding_token_is_current(token):
                self._set_unresolved_recovery(
                    "page-binding-changed-before-refresh",
                    request_id=request_id,
                    trigger=trigger,
                )
                return False
            browser = self._gpt_browser()
            try:
                page = await browser.page_by_handle(handle)
                current_target = str(getattr(page, "target_id", "") or "")
                if self.target_id and current_target and current_target != self.target_id:
                    raise RuntimeError("bound page target changed before refresh")
                current_url = str(getattr(page, "url", "") or "")
                if not current_url and hasattr(browser, "snapshot"):
                    observed = ChatSnapshot.from_bridge(
                        await browser.snapshot(
                            page,
                            signals=self.config.workflow.bridge_signals(),
                        )
                    )
                    current_url = observed.url
                if current_url and canonical_chat_url(current_url) != bound_url:
                    raise RuntimeError("bound page conversation URL changed before refresh")
                if not current_url or not url_matches_provider_session(
                    current_url, self.provider_session_id
                ):
                    raise RuntimeError("bound page provider session changed before refresh")
                await browser.navigate(page, bound_url)
                await asyncio.sleep(self.config.turn.poll_interval_seconds)
                if handle != self.page_handle:
                    raise RuntimeError("bound page handle changed during refresh")
                refreshed_page = await browser.page_by_handle(handle)
                refreshed_target = str(getattr(refreshed_page, "target_id", "") or "")
                refreshed_url = str(getattr(refreshed_page, "url", "") or "")
                if not refreshed_url and hasattr(browser, "snapshot"):
                    observed = ChatSnapshot.from_bridge(
                        await browser.snapshot(
                            refreshed_page,
                            signals=self.config.workflow.bridge_signals(),
                        )
                    )
                    refreshed_url = observed.url
                if self.target_id and refreshed_target and refreshed_target != self.target_id:
                    raise RuntimeError("bound page target changed after refresh")
                if (
                    not refreshed_url
                    or canonical_chat_url(refreshed_url) != bound_url
                    or not url_matches_provider_session(
                        refreshed_url, self.provider_session_id
                    )
                ):
                    raise RuntimeError("refresh left the bound conversation URL")
                logger.info(
                    "gpt-auto refreshed bound conversation trigger=%s request_id=%s",
                    trigger,
                    request_id,
                )
                return True
            except Exception as exc:  # noqa: BLE001 - caller owns bounded retry policy
                self._set_unresolved_recovery(
                    "refresh-failed",
                    request_id=request_id,
                    trigger=trigger,
                    exception_type=type(exc).__name__,
                    exception=str(exc),
                )
                return False

    async def _refresh_for_reconciliation(self) -> bool:
        """Compatibility wrapper for the one-shot unresolved reconciler."""
        if self._reconciliation_refresh_attempted:
            return False
        self._reconciliation_refresh_attempted = True
        expected = self._binding_token(self._last_snapshot) if self._last_snapshot else None
        return await self.refresh_bound_conversation(
            request_id=getattr(self, "unresolved_turn_id", None),
            expected_binding=expected,
            trigger="unresolved-reconciliation",
        )

    async def _refresh_for_response_recovery(self) -> bool:
        """Compatibility wrapper for callers using the old recovery name."""
        return await self.refresh_bound_conversation(trigger="response-recovery")

    async def find_prompt_snapshot(
        self, baseline: ChatSnapshot, expected_text: str
    ) -> ChatSnapshot | None:
        """Find a newly accepted prompt across duplicate retained tabs.

        Browser tabs can momentarily diverge after a restart.  The durable
        provider conversation URL is not enough to select the active tab, so
        use the provider's stable user-message UUID (with text as a bounded
        fallback) and rebind this chat to the matching target.
        """
        browser = self._gpt_browser()
        pages = await self.runtime.bridge.call("list_pages")
        if not isinstance(pages, list):
            return None
        old_handle = self.page_handle
        belongs = getattr(self.runtime, "page_belongs_to_dedicated_window", lambda _: True)
        for record in pages:
            handle = str(record.get("pageHandle") or "")
            if not handle or not belongs(record):
                continue
            if self.provider_session_id and not url_matches_provider_session(
                str(record.get("url") or ""), self.provider_session_id
            ):
                continue
            if handle != old_handle and not self._claim_page(handle):
                continue
            try:
                page = await browser.page_by_handle(handle)
                snapshot = ChatSnapshot.from_bridge(
                    await browser.snapshot(
                        page, signals=self.config.workflow.bridge_signals()
                    )
                )
            except Exception:  # noqa: BLE001 - one stale tab must not abort scan
                if handle != old_handle:
                    self.runtime.release_page(self, handle)
                continue
            fresh = bool(
                snapshot.latest_user_id
                and snapshot.latest_user_id not in set(baseline.user_message_ids)
            ) or snapshot.user_count > baseline.user_count
            if fresh and match_prompt(
                expected_text, snapshot.latest_user_correlation_text() or ""
            ):
                if old_handle and old_handle != handle:
                    self.runtime.release_page(self, old_handle)
                self._bind_page(record)
                self._last_snapshot = snapshot
                self._last_url = snapshot.url
                return snapshot
            if handle != old_handle:
                self.runtime.release_page(self, handle)
        return None

    async def _prefer_active_conversation_page(self) -> None:
        """Bind the matching tab with the richest mounted conversation DOM."""
        if not self.provider_session_id:
            return
        browser = self._gpt_browser()
        pages = await self.runtime.bridge.call("list_pages")
        if not isinstance(pages, list):
            return
        belongs = getattr(self.runtime, "page_belongs_to_dedicated_window", lambda _: True)
        candidates: list[tuple[tuple[int, int], dict, ChatSnapshot]] = []
        for record in pages:
            handle = str(record.get("pageHandle") or "")
            if (
                not handle
                or not belongs(record)
                or not url_matches_provider_session(
                    str(record.get("url") or ""), self.provider_session_id
                )
            ):
                continue
            try:
                page = await browser.page_by_handle(handle)
                snapshot = ChatSnapshot.from_bridge(
                    await browser.snapshot(
                        page, signals=self.config.workflow.bridge_signals()
                    )
                )
            except Exception:  # noqa: BLE001 - retain existing binding if a tab is stale
                continue
            candidates.append(((snapshot.user_count, snapshot.assistant_count), record, snapshot))
        if not candidates:
            return
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_record, best_snapshot = candidates[0]
        if len(candidates) > 1 and candidates[1][0] == best_score:
            raise RuntimeError(
                "gpt-auto retained conversation remains ambiguous after DOM reconciliation"
            )
        best_handle = str(best_record["pageHandle"])
        if best_handle == self.page_handle:
            self._last_snapshot = best_snapshot
            return
        if not self._claim_page(best_handle):
            raise RuntimeError("gpt-auto richest retained conversation page is already owned")
        old_handle = self.page_handle
        self._bind_page(best_record)
        if old_handle:
            self.runtime.release_page(self, old_handle)
        self._last_snapshot = best_snapshot
        self._last_url = best_snapshot.url

    def observed_status(self) -> dict[str, object]:
        """Return sparse page evidence for status projections."""
        if self._last_snapshot is None:
            return {}
        return self._last_snapshot.observe().as_mapping()

    async def publish_conversation_title(self, title: str | None) -> None:
        """Persist the current left-panel conversation label when it changes."""
        normalized = normalize_chat_title(title)
        if not normalized:
            return
        async with self._title_publish_lock:
            self._pending_conversation_title = normalized
            if not self.provider_session_id or normalized == self.conversation_title:
                return
            result = self.binding_sink(
                ProviderSessionBindingUpdate(
                    provider_session_ref=ProviderSessionRef(self.provider_session_id),
                    metadata={"chat-title": normalized},
                )
            )
            if asyncio.iscoroutine(result):
                await result
            # This is the last successfully persisted value, not last seen.
            self.conversation_title = normalized
            self._pending_conversation_title = None

    async def acquire_provider_identity(self, initial: ChatSnapshot | None = None) -> ChatSnapshot:
        self._move(ChatState.ACQUIRING_SESSION_ID)
        deadline = asyncio.get_running_loop().time() + self.config.chat.navigation_timeout_seconds
        snap = initial
        while asyncio.get_running_loop().time() < deadline:
            snap = snap or await self.snapshot()
            provider_id = parse_provider_session_id(snap.url)
            if provider_id:
                expected_project_id = parse_project_id(self.project_url or "")
                observed_project_id = parse_project_id(snap.url)
                if not expected_project_id or observed_project_id != expected_project_id:
                    self._move(ChatState.FAILED)
                    raise AudiaGenticError(
                        code="RES-GPTAUTO-006",
                        kind="providers",
                        message=(
                            "gpt-auto conversation was created outside the admitted "
                            "ChatGPT Project"
                        ),
                        details={
                            "phase": "provider-identity-acquisition",
                            "expected-project-id": expected_project_id,
                            "observed-project-id": observed_project_id,
                            "submission-attempted": True,
                        },
                    )
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
                            **(
                                {"chat-title": snap.conversation_title}
                                if snap.conversation_title
                                else {}
                            ),
                        },
                    )
                )
                if asyncio.iscoroutine(result):
                    await result
                self.provider_session_id = provider_id
                self.chat_url = chat_url
                title = snap.conversation_title or self._pending_conversation_title
                if title:
                    try:
                        await self.publish_conversation_title(title)
                    except Exception:
                        logger.debug("gpt-auto deferred title persistence failed; will retry", exc_info=True)
                claim_conversation = getattr(self.runtime, "claim_conversation", None)
                if claim_conversation is not None and not claim_conversation(self, provider_id):
                    self._move(ChatState.FAILED)
                    raise RuntimeError("gpt-auto provider conversation is already owned")
                # Cancellation/recovery may have won the race while the
                # conversation URL was being acquired.  Persist identity,
                # but never promote a recovering chat back into admission.
                if self.state is not ChatState.RECOVERING:
                    self._move(ChatState.BUSY)
                return snap
            snap = None
            await asyncio.sleep(0.2)
        self._move(ChatState.FAILED)
        raise RuntimeError("ChatGPT accepted the turn but no provider session id appeared")

    async def page_lost(self, handle: str) -> None:
        if handle != self.page_handle or self.state is ChatState.CLOSED:
            return
        self.page_handle = None
        self._page_generation += 1
        self.runtime.release_page(self, handle)
        self._lost_during_turn = self.active_turn_id is not None
        if self.state is not ChatState.RECOVERING:
            self._move(ChatState.RECOVERING)
        if not self._lost_during_turn:
            # GP12: an idle chat losing its page (e.g. the user closes the
            # tab) is not a crash to recover from immediately -- forcing an
            # unconditional recreate-and-navigate here means the tab can
            # never actually stay closed.  Mirror GptAutoProviderRuntime
            # .recover()'s own idle/active distinction: only a turn actively
            # in flight needs eager reconciliation to avoid losing it. An
            # idle chat's existing lazy ensure_ready() -> reconcile() path
            # (see there) already handles recovery on next real use.
            return
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
                if self.unresolved_turn_pending:
                    async with self._reconciliation_lock:
                        if await self._release_after_terminal_provider_error(error):
                            self._move(ChatState.READY)
                            return True
                        if not await self._reconcile_unresolved_turn():
                            return True
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

    async def _release_after_terminal_provider_error(self, error: BaseException) -> bool:
        """Release an unresolved fence after a request-owned provider error.

        A response-failure policy match is already a provider terminal
        decision made by the active turn watcher.  Requiring a later assistant
        response to reconcile that same turn is incorrect: the provider has
        explicitly rejected it, and the next prompt may safely reuse the
        conversation once the composer is idle.  Keep this path narrow so
        ambiguous submission, auth, and active-generation failures remain
        fail-closed.
        """
        if not isinstance(error, AudiaGenticError):
            return False
        details = error.details or {}
        if (
            error.code != "EXT-GPTAUTO-003"
            or details.get("failure-reason") != "provider-failure-policy-matched"
            or details.get("phase") != "response-observation"
        ):
            return False
        evidence = details.get("evidence")
        if not isinstance(evidence, (list, tuple, set)):
            return False
        evidence = {str(item) for item in evidence}
        if not evidence.intersection({"error-page", "error-alert"}):
            return False
        if "auth-required" in evidence:
            return False
        stable: ChatSnapshot | None = None
        binding_token: tuple[object, ...] | None = None
        for _ in range(2):
            try:
                snapshot = await self.snapshot(allow_recovering=True)
            except Exception:
                return False
            busy_signals = {
                "streaming-indicator",
                "thinking-indicator",
                "busy-indicator",
            }
            if (
                "auth-required" in snapshot.dom_signals
                or snapshot.generating
                or not snapshot.composer_present
                or not snapshot.composer_editable
                or not (
                    snapshot.error_present
                    or snapshot.dom_signals.intersection({"error-page", "error-alert"})
                )
                or snapshot.dom_signals.intersection(busy_signals)
            ):
                return False
            if not _terminal_error_request_owned(self, snapshot):
                return False
            if stable is not None and snapshot != stable:
                return False
            if binding_token is None:
                binding_token = self._binding_token(snapshot)
            stable = snapshot
            await asyncio.sleep(self.config.turn.response_stability_seconds)
        if binding_token is None or not await self._binding_token_is_current(binding_token):
            return False
        await self.persist_unresolved_clear()
        self.clear_unresolved_turn()
        self._reconciled_binding_token = binding_token
        self._set_unresolved_recovery(
            "request-owned-provider-error-released",
            evidence=sorted(evidence.intersection({"error-page", "error-alert"})),
        )
        return True

    def bridge_replaced(self) -> None:
        """Invalidate bridge-local binding before runtime-level recovery."""
        if self.page_handle is not None:
            self._page_generation += 1
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
            find_page = getattr(self.runtime, "find_conversation_page", None)
            page = (
                await find_page(
                    self.provider_session_id,
                    preferred_target_id=self.target_id,
                )
                if find_page is not None
                else next(
                    (
                        item
                        for item in pages
                        if url_matches_provider_session(
                            str(item.get("url") or ""),
                            self.provider_session_id,
                        )
                    ),
                    None,
                )
            )
            if page is not None and self._claim_page(str(page["pageHandle"])):
                self._bind_page(page)
                await self._prefer_active_conversation_page()
                if self.active_turn_id:
                    self._move(ChatState.BUSY)
                else:
                    if self.unresolved_turn_pending and not await self._reconcile_unresolved_turn():
                        return
                    await self.wait_quiescent(allow_recovering=True)
                    self._move(ChatState.READY)
                return
            if not self.chat_url:
                self._set_unresolved_recovery(
                    "provider-conversation-not-found",
                    provider_session_id=self.provider_session_id,
                    reason="durable-chat-url-missing",
                )
                if self.state is ChatState.RECOVERING:
                    self._move(ChatState.FAILED)
                return
            self.page_handle = await self._create_recovery_page()
            if not self.runtime.claim_page(self, self.page_handle):
                raise RuntimeError("gpt-auto created a page already owned by another session")
            try:
                await self.runtime.bridge.call(
                    "navigate",
                    {
                        "pageHandle": self.page_handle,
                        "url": self.chat_url,
                        "timeoutMs": int(self.config.chat.navigation_timeout_seconds * 1000),
                    },
                )
                snapshot = await self._wait_ready()
            except Exception:
                handle, self.page_handle = self.page_handle, None
                self.runtime.release_page(self, handle)
                raise
            if snapshot is not None and not url_matches_provider_session(
                snapshot.url, self.provider_session_id
            ):
                await self._retire_missing_provider_conversation(snapshot.url)
                return
            if self.active_turn_id:
                self._move(ChatState.BUSY)
            else:
                if self.unresolved_turn_pending and not await self._reconcile_unresolved_turn():
                    return
                self._move(ChatState.READY)
            return
        if self.target_id:
            stable = [page for page in pages if str(page.get("targetId") or "") == self.target_id]
            if len(stable) == 1 and self._claim_page(str(stable[0]["pageHandle"])):
                self._bind_page(stable[0])
                if self.active_turn_id:
                    self._move(ChatState.BUSY)
                else:
                    if self.unresolved_turn_pending and not await self._reconcile_unresolved_turn():
                        return
                    await self.wait_quiescent(allow_recovering=True)
                    self._move(ChatState.READY)
                return
        if self.active_turn_id:
            exact = [page for page in pages if page.get("url") == self._last_url]
            if len(exact) == 1 and self._claim_page(str(exact[0]["pageHandle"])):
                self._bind_page(exact[0])
                self._move(ChatState.BUSY)
                return
            self._move(ChatState.FAILED)
            return
        if self.unresolved_turn_pending:
            # No provider URL or stable target remains.  A fresh project page
            # cannot prove what happened to the prior Send, so retain the
            # session in RECOVERING instead of admitting a new prompt.
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

    async def _retire_missing_provider_conversation(self, observed_url: str) -> None:
        """Fail and remove a recovery tab when its durable chat was deleted.

        ChatGPT commonly redirects a deleted conversation URL to the owning
        project workspace. That workspace is not an equivalent conversation;
        accepting it would make every recovery cycle reopen a misleading tab.
        """
        handle, self.page_handle = self.page_handle, None
        self.runtime.release_page(self, handle)
        self._set_unresolved_recovery(
            "provider-conversation-not-found",
            provider_session_id=self.provider_session_id,
            observed_url=observed_url,
        )
        if handle:
            try:
                await self.runtime.bridge.call("close_page", {"pageHandle": handle})
            except Exception:
                logger.debug("failed to close deleted gpt-auto recovery tab", exc_info=True)
        if self.state is ChatState.RECOVERING:
            self._move(ChatState.FAILED)

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
        close_on_session_close = bool(
            self.runtime.config.browser.close_tabs_on_session_close
        )
        if handle and not close_on_session_close:
            retain = getattr(self.runtime, "retain_detached_page", None)
            if callable(retain):
                retain(self, handle, self._last_validated_activity_monotonic)
        self.runtime.release_page(self, handle)
        self._move(ChatState.CLOSED)
        self.runtime.unregister_chat(self)
        if handle and close_on_session_close:
            try:
                await self.runtime.bridge.call("close_page", {"pageHandle": handle})
            except Exception:
                pass


def _recoverable_turn_failure(error: BaseException) -> bool:
    """Classify only provider turn failures known to preserve the page."""
    return isinstance(error, AudiaGenticError) and error.code in {
        "EXT-GPTAUTO-002",
        "EXT-GPTAUTO-003",
        "EXT-GPTAUTO-004",
    }


def provider_quiescent(snapshot: ChatSnapshot) -> bool:
    """Return whether the provider can accept another turn.

    ``stop-control`` is deliberately *not* a blocking signal here.  ChatGPT
    has been observed to leave the stop button mounted after a response has
    completed (with ``generating`` already false); treating that stale widget
    as authoritative strands an otherwise usable persistent conversation and
    causes every subsequent turn to fail readiness.  The actual generation
    flag plus streaming/thinking/busy indicators remain blocking evidence.
    """
    # The stop button is advisory only: it can stick after completion.  Do not
    # let a stale renderer control override the provider's generation state.
    busy_signals = {"streaming-indicator", "thinking-indicator", "busy-indicator"}
    failed_signals = {"auth-required", "error-page", "error-alert"}
    return bool(
        snapshot.composer_present
        and snapshot.composer_editable
        and not snapshot.generating
        and not snapshot.error_present
        and not snapshot.dom_signals.intersection(busy_signals | failed_signals)
    )


def _reconciliation_completion_candidate(chat: PersistentChat, snapshot: ChatSnapshot) -> bool:
    """Return whether a snapshot is an initial request-owned terminal witness.

    This is deliberately a read-only preflight used before provider-side
    recovery controls.  It mirrors the correlation and completion gates below
    so a stale Retry/error panel cannot regenerate an already-complete turn.
    """
    if "auth-required" in snapshot.dom_signals:
        return False
    assistant_id = snapshot.latest_assistant_id
    if not assistant_id or not snapshot.latest_assistant_text:
        return False
    groups = chat.config.workflow.policy("response-complete").any_of_groups
    true_facts = snapshot.dom_signals | (
        {"not-generating"} if not snapshot.generating else set()
    )
    if groups and not any(group <= true_facts for group in groups):
        return False
    prompt_match, prompt_reason, _ = _unresolved_prompt_match_diagnostics(chat, snapshot)
    if prompt_match is None:
        expected = chat.unresolved_assistant_message_id
        return bool(expected and assistant_id == expected)
    if not chat.unresolved_assistant_message_id:
        return assistant_id != chat.unresolved_assistant_before_id
    if assistant_id == chat.unresolved_assistant_message_id:
        return True
    return bool(
        prompt_reason == "prompt-id-match"
        and snapshot.latest_user_id == chat.unresolved_prompt_message_id
        and snapshot.user_count
        == int(
            chat._checkpoint_metadata.get(
                "unresolved-baseline-user-count", snapshot.user_count
            )
        )
        and assistant_id != chat.unresolved_assistant_before_id
    )


def _reconciliation_evidence_clear(
    snapshot: ChatSnapshot, *, allow_terminal_errors: bool = False
) -> bool:
    """Whether a snapshot's own evidence proves a PRIOR turn is done.

    Deliberately narrower-scoped than provider_quiescent(): this answers
    "did the retained prompt reach a terminal outcome," not "is it safe to
    type a new prompt right now" -- reconciliation never submits anything.
    stop-control is excluded from the busy check here -- proven live
    (2026-08-15/16) to stick indefinitely after real completion, so it
    must not block reconciliation of an already-finished turn or admission
    of the next turn when the actual generation state is idle.
    """
    busy_signals = {"streaming-indicator", "thinking-indicator", "busy-indicator"}
    failed_signals = {"auth-required"}
    if not allow_terminal_errors:
        failed_signals.update({"error-page", "error-alert"})
    return bool(
        snapshot.composer_present
        and snapshot.composer_editable
        and not snapshot.error_present
        and not snapshot.dom_signals.intersection(busy_signals | failed_signals)
    )


def _terminal_error_request_owned(chat: PersistentChat, snapshot: ChatSnapshot) -> bool:
    """Require the explicit provider error to belong to this admitted turn."""
    if chat.unresolved_prompt_message_id:
        return snapshot.latest_user_id == chat.unresolved_prompt_message_id
    if not chat.unresolved_prompt_text_digest or not snapshot.latest_user_text:
        return False
    if (
        PromptFingerprint.from_text(snapshot.latest_user_text).digest
        != chat.unresolved_prompt_text_digest
    ):
        return False
    baseline_count = chat._checkpoint_metadata.get("unresolved-baseline-user-count")
    return baseline_count is None or snapshot.user_count > int(baseline_count)


def _metadata_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if key == "chat-title":
        return normalize_chat_title(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metadata_bool(metadata: dict[str, object], key: str) -> bool:
    return metadata.get(key) is True


def _unresolved_prompt_match(chat: PersistentChat, snapshot: ChatSnapshot) -> str | None:
    """Return a bounded prompt correlation key, or None when ambiguous.

    Provider message IDs are strongest.  When ChatGPT does not expose one,
    compare the mounted conversation sections by a persisted text digest.  A
    digest match is accepted only when exactly one visible section matches;
    repeated identical prompts remain unresolved instead of guessing.
    """
    return _unresolved_prompt_match_diagnostics(chat, snapshot)[0]


def _unresolved_prompt_match_diagnostics(
    chat: PersistentChat, snapshot: ChatSnapshot
) -> tuple[str | None, str, dict[str, object]]:
    """Correlate an unresolved prompt and explain every failed fallback.

    IDs are preferred, but a missing or stale provider ID is not itself a
    terminal error.  We then use the persisted text digest, accepting it only
    when exactly one visible user section matches.  Returning a reason and
    sparse evidence keeps the recovery decision inspectable without making
    callers infer it from a generic boolean.
    """
    prompt_id = chat.unresolved_prompt_message_id
    if prompt_id:
        if snapshot.latest_user_id == prompt_id and prompt_id in snapshot.user_message_ids:
            return f"id:{prompt_id}", "prompt-id-match", {"prompt-id": prompt_id}
        id_details: dict[str, object] = {
            "expected-prompt-id": prompt_id,
        }
        if snapshot.latest_user_id:
            id_details["observed-latest-user-id"] = snapshot.latest_user_id
    else:
        id_details = {}

    digest = chat.unresolved_prompt_text_digest
    if not digest:
        return None, "prompt-correlation-evidence-missing", id_details
    user_refs = snapshot.user_prompt_refs()
    observed_candidates = tuple(
        (ref.correlation_text or ref.text or "", ref)
        for ref in user_refs
        if ref.correlation_text or ref.text
    )
    if not observed_candidates:
        observed_candidates = tuple(
            (text, None)
            for text in (
                snapshot.user_message_texts
                or ((snapshot.latest_user_text,) if snapshot.latest_user_text else ())
            )
        )
    matches = [
        (text, ref)
        for text, ref in observed_candidates
        if PromptFingerprint.from_text(text).digest == digest
    ]
    if len(matches) == 1:
        text, ref = matches[0]
        details = {
            "prompt-text-digest": digest,
            "matched-user-count": len(matches),
        }
        if ref is not None and ref.correlation_text:
            details.update(
                {
                    "prompt-correlation-match": True,
                    "prompt-proof-source": "gpt-auto-dom-structural-v1",
                    "observed-correlation-text-length": len(ref.correlation_text),
                    "structural-hr-count": ref.structural_hr_count,
                }
            )
        if id_details:
            details.update(id_details)
            return f"text:{digest}", "prompt-id-mismatch-text-digest-match", details
        return f"text:{digest}", "prompt-text-digest-match", details
    if not matches:
        details = {
            **id_details,
            "expected-prompt-text-digest": digest,
            "observed-user-count": len(observed_candidates),
        }
        return None, "prompt-text-digest-not-found", details
    return None, "prompt-text-digest-ambiguous", {
        **id_details,
        "expected-prompt-text-digest": digest,
        "matching-user-count": len(matches),
    }


def _same_quiescent_state(left: ChatSnapshot, right: ChatSnapshot) -> bool:
    return (
        left.url,
        left.user_count,
        left.assistant_count,
        left.latest_assistant_id,
        left.latest_assistant_text,
    ) == (
        right.url,
        right.user_count,
        right.assistant_count,
        right.latest_assistant_id,
        right.latest_assistant_text,
    )


def _unresolved_observation_details(snapshot: ChatSnapshot | None) -> dict[str, object]:
    """Expose sparse evidence explaining why an unresolved turn stayed gated."""
    if snapshot is None:
        return {}
    details: dict[str, object] = {
        "observed-url": snapshot.url,
        "observed-user-count": snapshot.user_count,
        "observed-assistant-count": snapshot.assistant_count,
        "observed-composer-present": snapshot.composer_present,
        "observed-composer-editable": snapshot.composer_editable,
        "observed-generating": snapshot.generating,
        "observed-error-present": snapshot.error_present,
    }
    if snapshot.latest_user_id:
        details["observed-latest-user-id"] = snapshot.latest_user_id
    if snapshot.latest_assistant_id:
        details["observed-latest-assistant-id"] = snapshot.latest_assistant_id
    if snapshot.dom_signals:
        details["observed-dom-signals"] = sorted(snapshot.dom_signals)
    return details

