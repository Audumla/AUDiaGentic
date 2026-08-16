"""Persistent provider chat with disposable page binding."""

from __future__ import annotations

import asyncio
import hashlib
import re
from enum import StrEnum

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingSink,
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)
from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .config import GptAutoConfig
from .runtime import GptAutoProviderRuntime
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
        checkpoint_sink=None,
        provider_session_id: str | None = None,
        chat_url: str | None = None,
        resume_provider_metadata: dict[str, object] | None = None,
    ) -> None:
        self.ag_session_id = ag_session_id
        self.project_name = project_name
        self.project_url = project_url
        self.provider_session_id = provider_session_id
        self.chat_url = chat_url
        self.page_handle: str | None = None
        self.target_id: str | None = None
        self.active_turn_id: str | None = None
        self.state = ChatState.OPENING
        self.runtime = runtime
        self.config = config
        self.binding_sink = binding_sink
        self.checkpoint_sink = checkpoint_sink
        self._lost_during_turn = False
        self._last_url: str | None = None
        self._last_snapshot: ChatSnapshot | None = None
        metadata = resume_provider_metadata or {}
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
        # Keep the last reconciliation decision separate from the durable
        # marker.  The marker says *a turn may still be outstanding*; this
        # evidence says why the latest attempt could not clear it.  It is
        # intentionally ephemeral and is surfaced in the next boundary error.
        self._unresolved_recovery_reason: str | None = None
        self._unresolved_recovery_details: dict[str, object] = {}
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

    async def persist_unresolved_clear(self) -> None:
        """Durably clear the checkpoint only after terminal proof."""
        sink = self.checkpoint_sink
        self._checkpoint_metadata = {}
        if sink is None:
            return
        result = sink(self.unresolved_metadata())
        if asyncio.iscoroutine(result):
            await result

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
                    await browser.navigate(page, "https://chatgpt.com/projects")
                    match = await browser.find_project_url(page, self.project_name)
                else:
                    await self.runtime.bridge.call(
                        "navigate",
                        {"pageHandle": self.page_handle, "url": "https://chatgpt.com/projects"},
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
        snap = await self.snapshot()
        if self.provider_session_id and not url_matches_provider_session(
            snap.url, self.provider_session_id
        ):
            self._move(ChatState.FAILED)
            raise RuntimeError("gpt-auto resumed page has conflicting provider session id")
        if self.provider_session_id and self.unresolved_turn_pending:
            # A resumed conversation with an unresolved Send is not ordinary
            # READY.  Keep admission closed until the exact prompt/response
            # outcome is reconciled (or leave it RECOVERING for lazy retry).
            self._move(ChatState.RECOVERING)
            await self._reconcile_unresolved_turn()
            if self.unresolved_turn_pending:
                return
        self._move(ChatState.READY)

    def _bind_page(self, page: dict) -> None:
        self.page_handle = str(page["pageHandle"])
        target_id = str(page.get("targetId") or "")
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
        if self.state is ChatState.RECOVERING:
            if self.page_handle and self.unresolved_turn_pending:
                if await self._reconcile_unresolved_turn():
                    self._move(ChatState.READY)
            else:
                pages = await self.runtime.bridge.call("list_pages")
                await self.reconcile(pages)
                if self.state is ChatState.RECOVERING and self.unresolved_turn_pending:
                    if await self._reconcile_unresolved_turn():
                        self._move(ChatState.READY)
        if self.state is not ChatState.READY:
            if self.state is ChatState.RECOVERING and self.unresolved_turn_pending:
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-004",
                    kind="providers",
                    message=(
                        "gpt-auto could not reconcile the previous turn; "
                        "the conversation remains recoverable and no prompt was sent"
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
        return snapshot

    async def _reconcile_unresolved_turn(self) -> bool:
        """Prove the retained prompt reached a terminal provider outcome."""
        if not self.unresolved_turn_pending:
            return True
        try:
            snapshot = await self.snapshot(allow_recovering=True)
        except Exception as exc:  # noqa: BLE001 - preserve diagnostic context
            self._set_unresolved_recovery(
                "snapshot-observation-failed",
                exception_type=type(exc).__name__,
                exception=str(exc),
            )
            return False
        if snapshot.generating:
            self._set_unresolved_recovery("provider-still-generating")
            return False
        if not provider_quiescent(snapshot):
            self._set_unresolved_recovery(
                "provider-not-quiescent",
                composer_present=snapshot.composer_present,
                composer_editable=snapshot.composer_editable,
                error_present=snapshot.error_present,
                dom_signals=sorted(snapshot.dom_signals),
            )
            return False
        prompt_match, prompt_reason, prompt_details = _unresolved_prompt_match_diagnostics(
            self, snapshot
        )
        if prompt_match is None:
            self._set_unresolved_recovery(prompt_reason, **prompt_details)
            return False
        assistant_id = snapshot.latest_assistant_id
        if not assistant_id:
            self._set_unresolved_recovery("assistant-response-id-not-observed")
            return False
        if not snapshot.latest_assistant_text:
            self._set_unresolved_recovery("assistant-response-text-not-observed")
            return False
        # A stable partial assistant message can look idle while ChatGPT is
        # still stalled in a tool-backed turn.  Require explicit terminal
        # evidence before clearing the unresolved marker; the caller receives
        # a structured recovery error when that evidence never appears.
        if "completion-control" not in snapshot.dom_signals:
            self._set_unresolved_recovery(
                "completion-evidence-missing",
                required_signal="completion-control",
                observed_dom_signals=sorted(snapshot.dom_signals),
            )
            return False
        if self.unresolved_assistant_message_id:
            terminal = assistant_id == self.unresolved_assistant_message_id
        else:
            terminal = assistant_id != self.unresolved_assistant_before_id
        if not terminal:
            self._set_unresolved_recovery(
                "assistant-response-not-terminal-match",
                observed_assistant_id=assistant_id,
                expected_assistant_id=self.unresolved_assistant_message_id,
                assistant_before_id=self.unresolved_assistant_before_id,
            )
            return False
        match_fingerprint = (prompt_match, assistant_id, snapshot.latest_assistant_text)
        if self._unresolved_match_fingerprint != match_fingerprint:
            self._unresolved_match_fingerprint = match_fingerprint
            self._set_unresolved_recovery(
                "awaiting-second-stable-observation",
                correlation=prompt_match,
                assistant_id=assistant_id,
            )
            return False
        self.clear_unresolved_turn()
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
        if prompt_text:
            self.unresolved_prompt_text_digest = _prompt_text_digest(prompt_text)

    def mark_prompt_submitted(
        self,
        prompt_id: str,
        assistant_before_id: str | None,
        prompt_text: str | None = None,
    ) -> None:
        self.unresolved_turn_pending = True
        self._unresolved_recovery_reason = None
        self._unresolved_recovery_details = {}
        self.unresolved_prompt_message_id = prompt_id
        self.unresolved_assistant_before_id = assistant_before_id
        if prompt_text:
            self.unresolved_prompt_text_digest = _prompt_text_digest(prompt_text)

    def mark_assistant_observed(self, assistant_id: str) -> None:
        self.unresolved_assistant_message_id = assistant_id

    def clear_unresolved_turn(self) -> None:
        self.unresolved_turn_pending = False
        self.unresolved_prompt_message_id = None
        self.unresolved_assistant_message_id = None
        self.unresolved_assistant_before_id = None
        self.unresolved_prompt_text_digest = None
        self._unresolved_match_fingerprint = None
        self._unresolved_recovery_reason = None
        self._unresolved_recovery_details = {}

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
            if fresh and _same_prompt(snapshot.latest_user_text, expected_text):
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

    async def acquire_provider_identity(self, initial: ChatSnapshot | None = None) -> ChatSnapshot:
        self._move(ChatState.ACQUIRING_SESSION_ID)
        deadline = asyncio.get_running_loop().time() + self.config.chat.navigation_timeout_seconds
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
                if self.unresolved_turn_pending:
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
        "EXT-GPTAUTO-004",
    }


def provider_quiescent(snapshot: ChatSnapshot) -> bool:
    """One provider-neutral-in-the-adapter definition of safe next-turn admission."""
    busy_signals = {"stop-control", "streaming-indicator", "thinking-indicator", "busy-indicator"}
    failed_signals = {"auth-required", "error-page", "error-alert"}
    return bool(
        snapshot.composer_present
        and snapshot.composer_editable
        and not snapshot.generating
        and not snapshot.error_present
        and not snapshot.dom_signals.intersection(busy_signals | failed_signals)
    )


def _same_prompt(actual: str | None, expected: str) -> bool:
    if not isinstance(actual, str):
        return False
    return actual.strip() == expected.strip()


def _metadata_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metadata_bool(metadata: dict[str, object], key: str) -> bool:
    return metadata.get(key) is True


def _prompt_text_digest(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
    observed_texts = snapshot.user_message_texts or (
        (snapshot.latest_user_text,) if snapshot.latest_user_text else ()
    )
    matches = [text for text in observed_texts if _prompt_text_digest(text) == digest]
    if len(matches) == 1:
        details = {"prompt-text-digest": digest, "matched-user-count": len(matches)}
        if id_details:
            details.update(id_details)
            return f"text:{digest}", "prompt-id-mismatch-text-digest-match", details
        return f"text:{digest}", "prompt-text-digest-match", details
    if not matches:
        details = {
            **id_details,
            "expected-prompt-text-digest": digest,
            "observed-user-count": len(observed_texts),
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
