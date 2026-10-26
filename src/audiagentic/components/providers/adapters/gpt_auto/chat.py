"""Persistent provider chat with disposable page binding."""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum
from urllib.parse import urlsplit

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingSink,
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)
from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .cdp.client import CdpError
from .config import GptAutoConfig
from .prompt_fingerprint import PromptFingerprint, match_prompt
from .runtime import GptAutoProviderRuntime, _snapshot_has_positive_conversation_evidence
from .snapshot import ChatSnapshot
from .urls import (
    canonical_chat_url,
    canonical_project_url,
    normalize_chat_title,
    parse_project_id,
    parse_provider_session_id,
    same_chat_identity,
    url_matches_provider_session,
)

logger = logging.getLogger(__name__)

_TERMINAL_CHECKPOINT_METADATA_KEYS = frozenset(
    {
        "unresolved-turn-pending",
        "unresolved-turn-id",
        "submission-state",
        "submission-attempt-id",
        "submission-stage",
        "send-intent-ever",
        "submission-proven",
        "submission-proof-source",
        "submission-recovery-claim",
        "submission-recovery-generation",
        "recovery-state",
        "prompt-text-digest",
        "unresolved-baseline-user-id",
        "unresolved-baseline-assistant-id",
        "unresolved-baseline-user-count",
        "unresolved-baseline-assistant-count",
        "unresolved-baseline-error-alert-occurrences",
    }
)


class ProviderBindingIntegrityError(RuntimeError):
    """A request-owned provider page no longer identifies the bound turn."""


class _ConversationLoadFailure(CdpError):
    """Carry the replacement tab's DOM proof to the admission boundary."""

    def __init__(self, snapshot: ChatSnapshot) -> None:
        super().__init__("gpt-auto replacement conversation still failed to load")
        self.snapshot = snapshot


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
        # CDP page handles are bridge-local, but the browser target identity
        # survives a gateway restart while the browser remains alive.  Keep it
        # as the durable preferred binding; runtime.find_conversation_page()
        # still falls back to the exact provider conversation URL when the
        # target has disappeared.
        metadata = resume_provider_metadata or {}
        self.target_id: str | None = _metadata_text(metadata, "target-id")
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
        self._session_checkpoint_sink = checkpoint_sink
        self._turn_session_checkpoint_sink = None
        self._request_checkpoint_sink = None
        self._lost_during_turn = False
        self._last_url: str | None = None
        self._last_snapshot: ChatSnapshot | None = None
        # Physical-tab reclamation uses only validated request/session
        # evidence. Raw polling, renderer churn, focus and foreign turns
        # never update this clock; emitted provider activity may.
        self._last_validated_activity_monotonic = time.monotonic()
        self._validated_activity_generation = 0
        self.conversation_title = _metadata_text(metadata, "chat-title")
        self._pending_conversation_title: str | None = None
        self._title_publish_lock = asyncio.Lock()
        self._reconciliation_lock = asyncio.Lock()
        # Every provider page mutation (currently refresh/reload) is
        # serialized against the page binding.  A response watcher and an
        # unresolved-turn reconciler must never navigate the same physical
        # tab concurrently or allow a stale page handle to win.
        self._page_mutation_lock = asyncio.Lock()
        self._reconcile_lock = asyncio.Lock()
        self._replacement_target_pending = False
        self._browser_generation_recovery = False
        self._page_mutation_owner_probe: Callable[[], bool] | None = None
        self._physical_idle_closed = False
        self._idle_closed_turn_id: str | None = None
        self.unresolved_prompt_message_id = _metadata_text(metadata, "prompt-message-id")
        self.unresolved_assistant_message_id = _metadata_text(metadata, "assistant-message-id")
        self.unresolved_assistant_before_id = _metadata_text(
            metadata, "assistant-before-message-id"
        )
        self.unresolved_prompt_text_digest = _metadata_text(metadata, "prompt-text-digest")
        self._submission_proven = _metadata_bool(metadata, "submission-proven")
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
        self._defer_page_creation_on_recovery = False
        # A retained exact-URL tab can survive a gateway restart while its
        # renderer is stuck on ChatGPT's conversation-load error page.  Keep a
        # small bounded replacement budget so recovery can attach a fresh
        # tab without creating an unbounded trail of failed tabs.  The count is
        # session metadata, not chat-instance state: restart recovery creates a
        # new PersistentChat and must not reset the provider-side safety bound.
        self._conversation_load_recovery_attempts = _metadata_int(
            metadata, "conversation-load-recovery-attempts"
        )
        self._conversation_load_recovery_revision = _metadata_int(
            metadata, "conversation-load-recovery-revision"
        )
        self._load_budget_observation = None
        self._checkpoint_metadata: dict[str, object] = {
            key: metadata[key]
            for key in (
                "recovery-state",
                "submission-state",
                "submission-attempt-id",
                "submission-stage",
                "send-intent-ever",
                "submission-proof-source",
                "submission-recovery-claim",
                "submission-recovery-generation",
                "unresolved-turn-id",
                "unresolved-baseline-user-id",
                "unresolved-baseline-assistant-id",
                "unresolved-baseline-user-count",
                "unresolved-baseline-assistant-count",
                "unresolved-baseline-error-alert-occurrences",
                "terminal-evidence",
                "conversation-load-recovery-attempts",
            )
            if key in metadata and metadata[key] not in (None, "")
        }
        self._terminal_checkpoint_finalization: dict[str, object] = {}
        self._recovery_ready = asyncio.Event()
        self._recovery_ready.set()

    async def persist_unresolved_checkpoint(
        self,
        *,
        turn_id: str,
        baseline: ChatSnapshot | None,
    ) -> None:
        """Persist a prepared checkpoint before any browser submission action."""
        self._reconciliation_delivery_retry_attempted = False
        load_recovery_attempts = self._conversation_load_recovery_attempts
        same_turn = self._checkpoint_metadata.get("unresolved-turn-id") == turn_id
        submission_attempt_id = self._checkpoint_metadata.get("submission-attempt-id") if same_turn else None
        attempt_metadata = {
            key: copy.deepcopy(self._checkpoint_metadata[key])
            for key in (
                "submission-stage", "send-intent-ever",
            )
            if same_turn and key in self._checkpoint_metadata
        }
        submission_state = "proven" if self._submission_proven else "prepared"
        self._checkpoint_metadata = {
            **attempt_metadata,
            "recovery-state": (
                "submission-proven" if self._submission_proven else "submission-prepared"
            ),
            "submission-state": submission_state,
            "unresolved-turn-id": turn_id,
        }
        # Proof is persisted after the dispatch-stage checkpoint. Preserve its
        # immutable attempt identity when rebuilding the provider metadata; the
        # gateway compares that identity under the session lock before it
        # accepts the transition from dispatching to proven.
        if isinstance(submission_attempt_id, str) and submission_attempt_id:
            self._checkpoint_metadata["submission-attempt-id"] = submission_attempt_id
        if self.unresolved_prompt_text_digest:
            self._checkpoint_metadata["prompt-text-digest"] = (
                self.unresolved_prompt_text_digest
            )
        if self._submission_proven:
            # The source is part of the proof contract consumed by the
            # request-owned checkpoint CAS. Rebuilding this metadata dict must
            # not drop the evidence that mark_prompt_submitted established.
            self._checkpoint_metadata["submission-proof-source"] = (
                "provider-user-message"
            )
        if load_recovery_attempts:
            self._checkpoint_metadata[
                "conversation-load-recovery-attempts"
            ] = load_recovery_attempts
        if baseline is not None:
            for key, value in (
                ("unresolved-baseline-user-id", baseline.latest_user_id),
                ("unresolved-baseline-assistant-id", baseline.latest_assistant_id),
                ("unresolved-baseline-user-count", baseline.user_count),
                ("unresolved-baseline-assistant-count", baseline.assistant_count),
                (
                    "unresolved-baseline-error-alert-occurrences",
                    [
                        {
                            "digest": digest,
                            "ownerPromptMessageId": owner,
                        }
                        for digest, owner in baseline.error_alert_occurrences
                    ],
                ),
            ):
                if value is not None and value != "":
                    self._checkpoint_metadata[key] = value
        await self._persist_checkpoint({**self.unresolved_metadata(), **self._checkpoint_metadata})

    async def mark_submission_dispatching(self, *, turn_id: str) -> None:
        """Persist the attempt identity before touching the browser composer.

        This is deliberately not evidence that Send was invoked. The durable
        ``send-intent-ever`` latch is advanced separately at the exact browser
        click boundary by ``persist_submission_stage``.
        """
        self._checkpoint_metadata.update(
            {
                "recovery-state": "side-effect-may-have-started",
                "submission-state": "dispatching",
                "submission-attempt-id": uuid.uuid4().hex,
                "submission-stage": "dispatching",
                "send-intent-ever": bool(
                    self._checkpoint_metadata.get("send-intent-ever", False)
                ),
                "unresolved-turn-id": turn_id,
            }
        )
        await self._persist_checkpoint({**self.unresolved_metadata(), **self._checkpoint_metadata})

    async def persist_submission_stage(self, *, turn_id: str, stage: str) -> str:
        """Durably record one monotonic, content-free browser-submit stage."""
        stage_order = {
            "dispatching": 0,
            "composer-focused": 1,
            "composer-filled": 2,
            "composer-validated": 3,
            "send-intent": 4,
            "send-click-acknowledged": 5,
        }
        if stage not in stage_order:
            raise ValueError("unknown gpt-auto submission stage")
        if self._checkpoint_metadata.get("unresolved-turn-id") != turn_id:
            raise RuntimeError("submission stage does not match the unresolved turn")
        attempt_id = self._checkpoint_metadata.get("submission-attempt-id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise RuntimeError("submission stage has no durable attempt identity")
        current_stage = self._checkpoint_metadata.get("submission-stage")
        if (
            isinstance(current_stage, str)
            and current_stage in stage_order
            and stage_order[stage] < stage_order[current_stage]
        ):
            raise RuntimeError("submission stage cannot move backwards")
        updated = dict(self._checkpoint_metadata)
        updated["submission-stage"] = stage
        if stage == "send-intent":
            # Sticky for the lifetime of this request/attempt. A click
            # acknowledgement is not provider acceptance, but once intent is
            # durable a restart must treat the outcome as ambiguous.
            updated["send-intent-ever"] = True
        await self._persist_checkpoint({**self.unresolved_metadata(), **updated})
        self._checkpoint_metadata = updated
        return attempt_id

    async def _persist_checkpoint(self, metadata: dict[str, object]) -> None:
        session_sink = self._turn_session_checkpoint_sink or self._session_checkpoint_sink
        sinks = (session_sink, self._request_checkpoint_sink)
        seen: set[int] = set()
        for sink in sinks:
            if sink is None or id(sink) in seen:
                continue
            seen.add(id(sink))
            result = sink(metadata)
            if inspect.isawaitable(result):
                await result

    @property
    def checkpoint_sink(self):
        """Compatibility view of the durable session checkpoint sink."""
        return self._session_checkpoint_sink

    @checkpoint_sink.setter
    def checkpoint_sink(self, sink) -> None:
        self._session_checkpoint_sink = sink

    def set_request_metadata_sink(self, sink) -> None:
        """Bind only the request leg; retain the durable session leg."""
        self._request_checkpoint_sink = sink

    def set_turn_session_checkpoint_sink(self, sink) -> None:
        """Use the FIFO owner's session writer instead of the opening writer."""
        self._turn_session_checkpoint_sink = sink

    def clear_turn_session_checkpoint_sink(self, expected_sink) -> bool:
        if self._turn_session_checkpoint_sink is not expected_sink:
            return False
        self._turn_session_checkpoint_sink = None
        return True

    async def persist_request_metadata(self, metadata: dict[str, object]) -> None:
        """Persist provider identity only to the current request leg."""
        sink = self._request_checkpoint_sink
        if sink is None:
            return
        result = sink(metadata)
        if inspect.isawaitable(result):
            await result

    async def persist_unresolved_identity(self) -> None:
        """Persist prompt identity without rewriting the pre-send baseline."""
        await self._persist_checkpoint(self.unresolved_metadata())

    async def persist_proven_unsent_clear(self) -> None:
        """Retire this exact no-Send attempt after independent DOM reconciliation."""
        checkpoint = self._checkpoint_metadata
        if (
            self._submission_proven
            or checkpoint.get("send-intent-ever") is not False
            or checkpoint.get("submission-stage") not in {
                "dispatching", "composer-focused", "composer-filled", "composer-validated",
            }
            or not checkpoint.get("submission-attempt-id")
        ):
            raise RuntimeError("unsent retirement requires an exact pre-Send attempt")
        await self._persist_checkpoint({
            "unresolved-turn-pending": False,
            "submission-state": "not_started",
            "submission-proven": False,
            "submission-attempt-id": checkpoint["submission-attempt-id"],
            "unresolved-turn-id": checkpoint["unresolved-turn-id"],
        })
        self._checkpoint_metadata = {}

    async def persist_unresolved_clear(self) -> None:
        """Durably clear the checkpoint only after terminal proof."""
        if (
            self._session_checkpoint_sink is None
            and self._turn_session_checkpoint_sink is None
            and self._request_checkpoint_sink is None
        ):
            self._checkpoint_metadata = {}
            return
        # Emit the intended durable state explicitly.  Callers may persist
        # before mutating the in-memory marker so a failed write cannot expose
        # READY and then resurrect an unresolved lock after restart.
        metadata: dict[str, object] = {
            "unresolved-turn-pending": False,
            "submission-state": "cleared",
        }
        # Budget authority is separate from submission-checkpoint cleanup.
        if self._conversation_load_recovery_attempts and self._last_snapshot is not None:
            await self._reset_load_recovery_budget_after_positive_snapshot(self._last_snapshot)
        if self._submission_proven:
            metadata["submission-proven"] = True
            for key, value in (
                ("prompt-message-id", self.unresolved_prompt_message_id),
                ("assistant-message-id", self.unresolved_assistant_message_id),
                ("assistant-before-message-id", self.unresolved_assistant_before_id),
                ("prompt-text-digest", self.unresolved_prompt_text_digest),
            ):
                if value:
                    metadata[key] = value
        await self._persist_checkpoint(metadata)
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

    def set_page_mutation_owner_probe(
        self, probe: Callable[[], bool] | None
    ) -> None:
        """Install a fail-closed owner fence for provider-side page mutations."""
        self._page_mutation_owner_probe = probe

    def _page_mutation_owner_is_live(self) -> bool:
        state = getattr(self, "state", None)
        if state in {ChatState.CLOSED, ChatState.FAILED}:
            return False
        probe = getattr(self, "_page_mutation_owner_probe", None)
        if probe is None:
            return True
        try:
            return bool(probe())
        except Exception:
            return False

    def _turn_requires_recovery_proof(self) -> bool:
        """Distinguish an unfinished send from retained terminal provenance."""
        # Terminal checkpoint clearing deliberately retains submission/message
        # evidence. That history must not require an active response observer
        # merely to reopen an idle conversation for its next admission.
        return self.unresolved_turn_pending or self.active_turn_id is not None

    async def _recovery_page_is_current(self, page: dict) -> bool:
        """Check exact conversation and live physical identity before admission."""
        url = str(page.get("url") or "")
        expected_project = parse_project_id(self.project_url or "")
        observed_project = parse_project_id(url)
        if (
            not self._page_mutation_owner_is_live()
            or not url_matches_provider_session(url, self.provider_session_id)
            or (self.chat_url and not same_chat_identity(url, self.chat_url))
            or (not self.chat_url and expected_project and observed_project and expected_project != observed_project)
        ):
            return False
        lookup = getattr(self.runtime, "page_record", None)
        if callable(lookup):
            current = await lookup(str(page.get("pageHandle") or ""))
            if (
                current is None
                or current.get("targetId") != page.get("targetId")
                or not same_chat_identity(str(current.get("url") or ""), url)
            ):
                return False
        return self._page_mutation_owner_is_live()

    async def _reopen_idle_conversation(self) -> dict | None:
        """Lazily reopen the exact saved conversation without foreground work."""
        reopen = getattr(self.runtime, "reopen_conversation_page", None)
        if (
            self._turn_requires_recovery_proof()
            or not self.chat_url
            or not callable(reopen)
            or self._conversation_load_recovery_exhausted()
            or not self._page_mutation_owner_is_live()
        ):
            return None
        page = await reopen(
            self.chat_url, owner_is_live=self._page_mutation_owner_is_live
        )
        if not await self._recovery_page_is_current(page):
            raise ProviderBindingIntegrityError("idle conversation changed during reopening")
        return page

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
        recover_chat = getattr(self.runtime, "recover_chat", None)
        if (
            self.provider_session_id and self.chat_url and self.unresolved_turn_pending
            and self._defer_unresolved_reconciliation and callable(recover_chat)
        ):
            self._move(ChatState.RECOVERING)
            await recover_chat(self)
            return
        await self.runtime.ensure_available()
        await self.runtime.register_chat(self)
        if not self._page_mutation_owner_is_live():
            raise ProviderBindingIntegrityError(
                "gpt-auto page mutation refused without a live durable owner"
            )
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
            if (
                page is not None
                and self.target_id
                and self._turn_requires_recovery_proof()
                and str(page.get("targetId") or "") != self.target_id
            ):
                self._set_unresolved_recovery(
                    "conversation-load-observation-deferred",
                    provider_session_id=self.provider_session_id,
                    chat_url=self.chat_url,
                    defer_reason="replacement-target-requires-explicit-reattach",
                    observed_target_id=str(page.get("targetId") or ""),
                    expected_target_id=self.target_id,
                )
                raise RuntimeError(
                    "gpt-auto unresolved provider conversation is attached to a replacement target"
                )
            if page is None:
                page = await self._reopen_idle_conversation()
                if page is None and self._conversation_load_recovery_exhausted():
                    raise self._conversation_load_failure_error()
            if page is not None:
                if not await self._recovery_page_is_current(page):
                    raise ProviderBindingIntegrityError("retained conversation changed before binding")
                if not self._claim_page(str(page["pageHandle"])):
                    raise RuntimeError("gpt-auto retained conversation page is already owned")
                self._bind_page(page)
                retained = await self._retained_page_snapshot()
                if not await self._replace_load_failed_page(retained):
                    if retained is not None and "conversation-load-failed" in retained.dom_signals:
                        # A retained unresolved turn is still owned by the
                        # provider. A load-error page is not evidence that
                        # the turn failed; the request observer retains the
                        # exact conversation until its outer timeout.
                        if (
                            self._turn_requires_recovery_proof()
                        ):
                            self._set_unresolved_recovery(
                                "conversation-load-observation-deferred",
                                observed_url=retained.url,
                                dom_signals=sorted(retained.dom_signals),
                            )
                        else:
                            raise self._conversation_load_failure_error(retained)
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
        if (
            self.page_handle is None
            and self.provider_session_id
            and self._turn_requires_recovery_proof()
        ):
            # The durable unresolved-turn fence is authoritative across a
            # gateway restart.  A reconstructed chat may not have the
            # in-memory defer flag that page_lost() set in the previous
            # process, but it must still never create a replacement tab for
            # an ambiguous provider-side Send.
            self._set_unresolved_recovery(
                "conversation-load-observation-deferred",
                provider_session_id=self.provider_session_id,
                chat_url=self.chat_url,
                defer_reason="durable-unresolved-turn-fence",
            )
            self._move(ChatState.RECOVERING)
            raise RuntimeError(
                "gpt-auto unresolved provider conversation is detached; "
                "recovery requires explicit exact-tab reattachment"
            )
        if (
            self.page_handle is None and self.provider_session_id
            and self._defer_page_creation_on_recovery
            and self._turn_requires_recovery_proof()
        ):
            self._move(ChatState.RECOVERING)
            raise RuntimeError("gpt-auto restart recovery deferred because the exact provider conversation tab is not attached")
        if (
            self.page_handle is None
            and self.provider_session_id
            and self._load_failure_requires_retained_observation()
        ):
            self._set_unresolved_recovery(
                "conversation-load-observation-deferred",
                provider_session_id=self.provider_session_id,
                chat_url=self.chat_url,
                defer_reason="exact-conversation-tab-detached",
            )
            self._move(ChatState.RECOVERING)
            raise RuntimeError(
                "gpt-auto unresolved provider conversation is detached; "
                "recovery requires explicit exact-tab reattachment"
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
        # An exact-bound restart observer must attach before the provider turn
        # becomes quiescent. GPT can spend minutes in reasoning with a visible
        # Stop control; requiring READY/quiescence here makes transport.open()
        # time out and leaves the request running with no live gateway session.
        # resume_existing() owns the response observer and never submits again.
        if not (
            self.provider_session_id
            and self.unresolved_turn_pending
            and self._defer_unresolved_reconciliation
        ):
            await self._wait_ready()
        # _wait_ready() already tolerates RECOVERING (it calls
        # wait_quiescent(allow_recovering=True)) -- a shared-bridge
        # replacement can race this exact resume window and move state to
        # RECOVERING between that call and this one. Without allow_recovering
        # here too, this would block for the full recovery-timeout waiting on
        # a signal nothing in this flow ever sets, before eventually failing
        # anyway -- a needless hang on the way to the same outcome.
        snap = await self.snapshot(allow_recovering=True)
        if self.provider_session_id and page is not None and not await self._recovery_page_is_current(page):
            raise ProviderBindingIntegrityError("retained conversation changed during readiness")
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

    def defer_unresolved_reconciliation(
        self, *, defer_page_creation: bool = False
    ) -> None:
        """Leave the checkpoint for the request-owned recovery turn.

        Gateway restart recovery must first reattach the exact conversation.
        The request-owned ``resume_existing`` turn is the only authority that
        may observe, persist the response artifact, and clear this checkpoint.
        """
        self._defer_unresolved_reconciliation = True
        self._defer_page_creation_on_recovery = defer_page_creation

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
        if self._physical_idle_closed:
            if self.active_turn_id and self.active_turn_id == self._idle_closed_turn_id:
                raise RuntimeError("physical tab was closed after session inactivity")
            # Only a new admission can reopen an intentionally reaped tab.
            self._physical_idle_closed = False
            self._idle_closed_turn_id = None
        # Bridge page handles are local to one CDP connection and can be
        # invalidated without the runtime seeing a Target event (for example,
        # an operator closes a tab through a second CDP client).  A handle can
        # even be recycled for an unrelated tab.  Validate the binding before
        # admitting a turn so the turn never fails with an opaque
        # ``unknown-or-closed-page`` error; recovery then rebinds by stable
        # target/provider URL and, if necessary, recreates the conversation tab.
        await self._validate_page_binding()
        if (
            self.provider_session_id
            and self.page_handle
            and self.state not in {ChatState.FAILED, ChatState.CLOSED}
        ):
            # A retained handle can remain valid while its document has been
            # replaced by ChatGPT's "Could not load this conversation" page.
            # Treat that DOM state as a binding failure before the deferred
            # resume shortcut below. Otherwise resume_existing() repeatedly
            # observes the same dead page, renews synthetic activity, and
            # presents false progress to the external client.
            retained = await self._retained_page_snapshot()
            if retained is not None and "conversation-load-failed" in retained.dom_signals:
                try:
                    replaced = await self._replace_load_failed_page(retained)
                except _ConversationLoadFailure as exc:
                    # A replacement can render the same provider error even
                    # though navigation itself succeeded. Preserve that DOM
                    # witness instead of downgrading it to generic readiness
                    # failure at the transport boundary.
                    raise self._conversation_load_failure_error(exc.snapshot) from exc
                if not replaced:
                    if (
                        self._turn_requires_recovery_proof()
                    ):
                        self._set_unresolved_recovery(
                            "conversation-load-observation-deferred",
                            observed_url=retained.url,
                            dom_signals=sorted(retained.dom_signals),
                        )
                    else:
                        raise self._conversation_load_failure_error(retained)
        if self.provider_session_id and not self.page_handle:
            # AS125 may have reclaimed only the physical tab. Reopen the
            # exact retained provider conversation before admitting a turn;
            # never fall through to a fresh ChatGPT conversation.
            self._move(ChatState.RECOVERING)
            pages = await self.runtime.bridge.call("list_pages")
            await self.reconcile(pages)
        if self.state is ChatState.RECOVERING:
            if (
                self.page_handle
                and self.unresolved_turn_pending
                and self._defer_unresolved_reconciliation
            ):
                # Restart recovery has already established the exact durable
                # provider binding.  The request-owned resume_existing turn
                # must observe the in-flight response loop directly; running
                # the terminal quiescence reconciler here would reject a
                # genuinely generating turn on every recovery retry.
                self._move(ChatState.READY)
            elif self.page_handle and self.unresolved_turn_pending:
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
        remember = getattr(self.runtime, "remember_tab_activity", None)
        if callable(remember):
            remember(self)

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
            if (
                not handle
                # A live provider turn is itself session activity.  Synthetic
                # transport heartbeats must not allow the physical-tab reaper
                # to close the only tab while the provider is still working.
                # Once the turn reaches a terminal state, the independent
                # validated-DOM inactivity clock may reclaim the tab again.
                or self.active_turn_id is not None
                or self.pending_turns > 0
                or now - self._last_validated_activity_monotonic < idle_timeout_seconds
            ):
                return False
            digest = getattr(self.runtime, "_tab_digest", None)
            before = getattr(self, "_last_snapshot", None)
            if callable(digest) and before is not None:
                try:
                    current = await self.snapshot(allow_recovering=True)
                    if same_chat_identity(current.url, before.url) and digest(current) != digest(before):
                        self.mark_validated_activity()
                        return False
                except Exception:
                    # Failure is not activity and cannot grant an unlimited
                    # retention exemption. The last validated clock still owns
                    # the physical cleanup deadline.
                    logger.debug("gpt-auto pre-cleanup observation failed", exc_info=True)
            if (
                handle != self.page_handle
                or self.active_turn_id is not None
                or self.pending_turns > 0
                or now - self._last_validated_activity_monotonic < idle_timeout_seconds
            ):
                return False
            self._physical_idle_closed = True
            self._idle_closed_turn_id = self.active_turn_id
            try:
                await self.runtime.bridge.call("close_page", {"pageHandle": handle})
            except Exception:
                self._physical_idle_closed = False
                self._idle_closed_turn_id = None
                logger.debug(
                    "gpt-auto physical idle-tab close failed",
                    extra={"session-id": self.ag_session_id, "page-handle": handle},
                    exc_info=True,
                )
                return False
            if handle != self.page_handle:
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
            else bool(chat_url and same_chat_identity(current_url, str(chat_url)))
        )
        return bool(
            (not target_id or not current_target or current_target == target_id)
            and same_conversation
            and bool(chat_url and same_chat_identity(current_url, str(chat_url)))
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

    async def _wait_ready(self) -> ChatSnapshot:
        return await self.wait_quiescent(allow_recovering=True)

    def _replacement_snapshot_is_positive(self, snapshot: ChatSnapshot | None) -> bool:
        """Require exact, positive DOM evidence before clearing recovery budget."""
        if snapshot is None or snapshot.error_present or "conversation-load-failed" in snapshot.dom_signals:
            return False
        if self.provider_session_id and not url_matches_provider_session(
            snapshot.url, self.provider_session_id
        ):
            return False
        if self.chat_url and not same_chat_identity(snapshot.url, self.chat_url):
            return False
        return _snapshot_has_positive_conversation_evidence(snapshot)

    async def _retained_page_snapshot(self) -> ChatSnapshot | None:
        """Read a retained page when the runtime exposes the rich browser API.

        Small bridge-only test/runtime seams intentionally expose only
        ``list_pages`` and navigation. They cannot prove a DOM load failure,
        so retain their historical URL-binding behavior.
        """
        browser = getattr(self.runtime, "gpt_browser", None) or getattr(
            self.runtime, "bridge", None
        )
        if browser is None:
            return None
        if not all(
            callable(getattr(browser, name, None))
            for name in ("page_by_handle", "snapshot")
        ):
            return None
        return await self.snapshot(allow_recovering=True)

    def _conversation_load_recovery_enabled(self) -> bool:
        config = getattr(self, "config", None)
        workflow = getattr(config, "workflow", None)
        recovery = getattr(workflow, "recovery", None)
        return bool(
            recovery is not None
            and getattr(recovery, "conversation_load_failure_recovery_enabled", True)
            and getattr(self, "chat_url", None)
        )

    async def _reset_load_recovery_budget_after_positive_snapshot(
        self, snapshot: ChatSnapshot
    ) -> None:
        """Clear replacement budget only after positive conversation proof."""
        if self.unresolved_turn_pending and self._defer_unresolved_reconciliation:
            return
        observation = self._load_budget_observation
        if (
            not self._replacement_snapshot_is_positive(snapshot)
            or observation is None or observation[0] is not snapshot
            or observation[2] != self._binding_token(snapshot)
            or observation[1] != (
                self._conversation_load_recovery_attempts,
                self._conversation_load_recovery_revision,
            )
            or not self._conversation_load_recovery_attempts
        ):
            return
        if (
            not await self._binding_token_is_current(observation[2])
            or observation[2] != self._binding_token(snapshot)
        ):
            return
        await self._persist_load_recovery_budget("reset", expected=observation[1])

    async def _persist_load_recovery_budget(
        self, action: str, *, expected: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        """Commit session authority before navigation; request copy is advisory."""
        maximum = self.config.workflow.recovery.conversation_load_failure_max_attempts
        if type(maximum) is not int or not 0 <= maximum <= 1_000_000:
            raise ValueError("invalid conversation load replacement budget")
        sink = self._turn_session_checkpoint_sink or self._session_checkpoint_sink
        budget_sink = getattr(sink, "recovery_budget", None)
        if sink is not None and not callable(budget_sink):
            raise RuntimeError("durable checkpoint sink has no recovery budget capability")
        if callable(budget_sink):
            result = await budget_sink(action=action, expected=expected, maximum=maximum)
        else:
            # Standalone provider use has no durable gateway or request owner.
            current = (self._conversation_load_recovery_attempts, self._conversation_load_recovery_revision)
            if action == "read":
                return current
            if expected != current or (action == "increment" and current[0] >= maximum):
                raise RuntimeError("conversation load budget compare-and-swap rejected")
            result = (current[0] + 1 if action == "increment" else 0, current[1] + 1)
        self._conversation_load_recovery_attempts, self._conversation_load_recovery_revision = result
        if action != "read":
            projection = dict(zip(("conversation-load-recovery-attempts", "conversation-load-recovery-revision"), result))
            self._checkpoint_metadata.update(projection)
            try:
                await self.persist_request_metadata(projection)
            except Exception:  # noqa: BLE001 - session commit is authoritative
                logger.warning("request recovery budget projection failed; session authority retained", exc_info=True)
            if callable(budget_sink):
                # Projection failure must not hide owner retirement before a side effect.
                await budget_sink(action="read", maximum=maximum)
        return result

    def _conversation_load_recovery_allowed(self) -> bool:
        workflow = getattr(self.config, "workflow", None)
        recovery = getattr(workflow, "recovery", None)
        return bool(
            self._conversation_load_recovery_enabled()
            and recovery is not None
            and self._conversation_load_recovery_attempts
            < max(
                0,
                int(getattr(recovery, "conversation_load_failure_max_attempts", 0)),
            )
        )

    def _conversation_load_recovery_exhausted(self) -> bool:
        """Return whether a failed conversation must remain observation-only.

        A missing exact tab is normally recoverable, but once the persisted
        replacement budget is exhausted, creating another tab just to render
        the same provider load-error page is not recovery.  In particular it
        must not be allowed to become a watchdog-driven tab creation loop.
        Keep the session recoverable for an operator/dashboard reattach and
        let the request's normal outer deadline decide its final state.
        """
        workflow = getattr(self.config, "workflow", None)
        recovery = getattr(workflow, "recovery", None)
        maximum = max(
            0,
            int(getattr(recovery, "conversation_load_failure_max_attempts", 0)),
        )
        return bool(
            self._conversation_load_recovery_attempts
            and self._conversation_load_recovery_attempts >= maximum
        )

    def _load_failure_requires_retained_observation(self) -> bool:
        """Return whether load recovery must stay on the exact conversation."""
        return bool(
            self._turn_requires_recovery_proof()
        )

    def _conversation_load_failure_error(
        self, snapshot: ChatSnapshot | None = None
    ) -> AudiaGenticError:
        """Build the terminal error for an exhausted failed-page recovery."""
        retained_observation = self._load_failure_requires_retained_observation()
        self._set_unresolved_recovery(
            "conversation-load-recovery-exhausted",
            attempts=self._conversation_load_recovery_attempts,
            provider_session_id=self.provider_session_id,
            chat_url=self.chat_url,
        )
        if self.state not in {ChatState.FAILED, ChatState.CLOSED}:
            self._move(ChatState.RECOVERING if retained_observation else ChatState.FAILED)
        details: dict[str, object] = {
            "failure-reason": "conversation-load-failed",
            "recovery-reason": "conversation-load-recovery-exhausted",
            "conversation-load-recovery-attempts": self._conversation_load_recovery_attempts,
            "submission-proven": self._submission_proven,
            # ``ensure_ready`` runs before a new GptAutoTurn exists, but it is
            # also used by restart observation.  Make the distinction
            # explicit so dispatch can rotate only an actually-unsent request;
            # a retained unresolved turn remains observation-only.
            "submission-attempted": bool(self.active_turn_id),
            "submission-ambiguous": bool(
                self.active_turn_id or self.unresolved_turn_pending
            ),
            "previous-turn-unresolved": bool(self.unresolved_turn_pending),
            "failure-stage": "readiness",
            "submission-state": "ambiguous" if retained_observation else "not_started",
            "submission-replay": False,
            "provider-session-id": self.provider_session_id,
            "chat-url": self.chat_url,
            **self._unresolved_recovery_diagnostics(),
        }
        if snapshot is not None:
            details.update(
                {
                    "dom-signals": sorted(snapshot.dom_signals),
                    "observed-url": snapshot.url,
                    "failure-response-available": bool(snapshot.latest_assistant_text),
                }
            )
        return AudiaGenticError(
            code="EXT-GPTAUTO-005",
            kind="providers",
            message=(
                "gpt-auto could not load the durable ChatGPT conversation after "
                "bounded recovery; the unresolved request was not replayed"
            ),
            details=details,
        )

    async def _restore_page_binding(self, page_handle: str | None) -> bool:
        """Restore the retained page after an unproven duplicate candidate."""
        if not page_handle:
            return False
        if self.page_handle == page_handle:
            return True
        if not self._claim_page(page_handle):
            return False
        previous = self.page_handle
        self.page_handle = page_handle
        page_record = getattr(self.runtime, "page_record", None)
        if callable(page_record):
            record = await page_record(page_handle)
            if record is not None:
                self._bind_page(record)
        if previous and previous != page_handle:
            self.runtime.release_page(self, previous)
        return True
    async def _replace_load_failed_page(self, snapshot: ChatSnapshot | None) -> bool:
        """Attach a new exact conversation tab after a retained tab load error.

        This is deliberately navigation-only.  It never submits the unresolved
        prompt and it never closes the retained tab that may still contain the
        provider-side turn.  A newly-created replacement that also fails to
        load is closed so repeated recovery cannot leak tabs.
        """
        if snapshot is None or "conversation-load-failed" not in snapshot.dom_signals:
            # The absence of the load-error marker is not, by itself, strong
            # healthy proof: deferred restart observation can see a transient
            # loading/generating snapshot before the provider turn is bound.
            # Keep a consumed budget until a replacement completes or the
            # unresolved checkpoint is terminally cleared.
            return False
        if not self._conversation_load_recovery_enabled():
            return False

        # Start the readiness budget before scanning duplicate tabs.  A long
        # exact-URL scan must not delay the provider Retry/failure boundary.
        retry_deadline = asyncio.get_running_loop().time() + max(
            0.0, float(self.config.chat.ready_timeout_seconds)
        )
        failed_handle = self.page_handle
        remaining = retry_deadline - asyncio.get_running_loop().time()
        # Duplicate-tab discovery is safe only before the browser-side
        # submission boundary. Once a turn is submitted or ambiguous, even an
        # exact-URL alternate can be a stale renderer and must not displace
        # the provider conversation being observed.
        browser_network_error = "browser-network-error" in snapshot.dom_signals
        if remaining > 0 and not browser_network_error and not self._load_failure_requires_retained_observation():
            try:
                async with asyncio.timeout(remaining):
                    await self._prefer_active_conversation_page()
                    if self.page_handle and self.page_handle != failed_handle:
                        alternate = await self.snapshot(allow_recovering=True)
                        if self._replacement_snapshot_is_positive(alternate):
                            await self._reset_load_recovery_budget_after_positive_snapshot(
                                alternate
                            )
                            self._set_unresolved_recovery(
                                "conversation-load-duplicate-recovered"
                            )
                            return True
                        await self._restore_page_binding(failed_handle)
            except TimeoutError:
                await self._restore_page_binding(failed_handle)
                self._set_unresolved_recovery(
                    "conversation-load-duplicate-observation-deadline"
                )

        # Prefer the provider's own Retry control on the retained conversation
        # before creating another tab.  This is observation recovery only: the
        # original prompt may already have executed, so no prompt is replayed.
        # Retry attempts are bounded by the normal readiness window and use
        # increasing delays so a transient renderer load failure can recover
        # without turning synthetic activity into an internal lease renewal.
        retry_delay = max(
            0.5,
            float(self.config.turn.poll_interval_seconds),
            float(getattr(self.config.workflow.recovery, "action_pause_seconds", 0.0)),
        )
        retry_attempts = 0
        while asyncio.get_running_loop().time() < retry_deadline:
            remaining = retry_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    clicked = await self.retry_conversation_load()
            except TimeoutError:
                self._set_unresolved_recovery(
                    "conversation-load-retry-deadline",
                    attempts=retry_attempts,
                )
                break
            except Exception as exc:  # noqa: BLE001 - preserve observation evidence
                self._set_unresolved_recovery(
                    "conversation-load-retry-failed",
                    exception_type=type(exc).__name__,
                    exception=str(exc),
                    attempts=retry_attempts,
                )
                break
            if not clicked:
                break
            retry_attempts += 1
            self._set_unresolved_recovery(
                "conversation-load-retry-clicked",
                attempts=retry_attempts,
                delay_seconds=retry_delay,
            )
            remaining = retry_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(retry_delay, remaining))
            remaining = retry_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    retried_snapshot = await self.snapshot(allow_recovering=True)
            except TimeoutError:
                self._set_unresolved_recovery(
                    "conversation-load-retry-observation-deadline",
                    attempts=retry_attempts,
                )
                break
            except Exception as exc:  # noqa: BLE001 - preserve observation evidence
                self._set_unresolved_recovery(
                    "conversation-load-retry-observation-failed",
                    exception_type=type(exc).__name__,
                    exception=str(exc),
                    attempts=retry_attempts,
                )
                break
            if "conversation-load-failed" not in retried_snapshot.dom_signals:
                if not self._replacement_snapshot_is_positive(retried_snapshot):
                    self._set_unresolved_recovery(
                        "conversation-load-retry-unproven",
                        attempts=retry_attempts,
                    )
                    break
                await self._reset_load_recovery_budget_after_positive_snapshot(
                    retried_snapshot
                )

                self._set_unresolved_recovery(
                    "conversation-load-retry-recovered",
                    attempts=retry_attempts,
                )
                return True
            retry_delay = min(retry_delay * 2.0, 8.0)

        # Same-tab Retry is independent of replacement-tab budget.
        # Replacement is unsafe once a turn was submitted or is ambiguous:
        # the provider may still own the original work. Keep this exact tab
        # bound and let the request observer retry its visible control.
        if self._turn_requires_recovery_proof():
            self._set_unresolved_recovery(
                "conversation-load-observation-deferred",
                attempts=retry_attempts,
                observed_url=snapshot.url,
                dom_signals=sorted(snapshot.dom_signals),
            )
            return True
        if browser_network_error:
            # A network outage is not repaired by multiplying tabs. Keep the
            # exact retained conversation; admission owns the outer deadline.
            self._set_unresolved_recovery(
                "conversation-load-retry-deadline", attempts=retry_attempts,
                dom_signals=sorted(snapshot.dom_signals),
            )
            return False
        if not self._page_mutation_owner_is_live():
            self._set_unresolved_recovery(
                "conversation-load-owner-not-live",
                attempts=retry_attempts,
            )
            return False
        current_budget = await self._persist_load_recovery_budget("read")
        if not self._conversation_load_recovery_allowed():
            return False
        old_handle = self.page_handle
        await self._persist_load_recovery_budget("increment", expected=current_budget)
        if not self._page_mutation_owner_is_live():
            return False
        if old_handle:
            self.page_handle = None
            self.runtime.release_page(self, old_handle)
        replacement_handle: str | None = None
        try:
            replacement_handle = await self._create_recovery_page()
            self.page_handle = replacement_handle
            if not self._claim_page(replacement_handle):
                raise RuntimeError("gpt-auto replacement conversation page is already owned")
            page_record = getattr(self.runtime, "page_record", None)
            if page_record is not None:
                record = await page_record(replacement_handle)
                if record is not None:
                    self._bind_page(record)
            if not self._page_mutation_owner_is_live():
                raise ProviderBindingIntegrityError(
                    "gpt-auto replacement navigation refused without a live durable owner"
                )
            await self.runtime.bridge.call(
                "navigate",
                {
                    "pageHandle": replacement_handle,
                    "url": self.chat_url,
                    "timeoutMs": int(self.config.chat.navigation_timeout_seconds * 1000),
                },
                timeout=self.config.chat.navigation_timeout_seconds + 2,
            )
            replacement = await self.snapshot(allow_recovering=True)
            if "conversation-load-failed" in replacement.dom_signals:
                raise _ConversationLoadFailure(replacement)
            # During restart recovery the provider may still be generating. A
            # request-owned resume turn must attach and observe immediately;
            # ordinary session opening still proves quiescence below.
            stable_replacement = self._replacement_snapshot_is_positive(replacement)
            if not self.unresolved_turn_pending or not self._defer_unresolved_reconciliation:
                ready_snapshot = await self._wait_ready()
                stable_replacement = stable_replacement and self._replacement_snapshot_is_positive(
                    ready_snapshot
                )
            # A deferred restart recovery is still observing an unresolved
            # provider turn. The replacement may look merely loadable before
            # ChatGPT surfaces a delayed conversation-load error, so retain
            # the consumed replacement budget until stable reconciliation or
            # explicit terminal cleanup.
            if stable_replacement and not (
                self.unresolved_turn_pending and self._defer_unresolved_reconciliation
            ):
                await self._reset_load_recovery_budget_after_positive_snapshot(ready_snapshot)
            return True
        except Exception:
            if replacement_handle:
                self.page_handle = None
                self.runtime.release_page(self, replacement_handle)
                try:
                    await self.runtime.bridge.call(
                        "close_page", {"pageHandle": replacement_handle}
                    )
                except Exception:
                    logger.debug(
                        "gpt-auto failed to close load-error replacement tab",
                        exc_info=True,
                    )
            raise

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
        """Read one bounded CDP snapshot without bounding the whole turn."""
        cdp_config = getattr(self.config, "cdp", None)
        protocol_timeout = float(
            getattr(cdp_config, "protocol_timeout_seconds", 30.0)
        )
        if protocol_timeout <= 0:
            protocol_timeout = 30.0
        return await asyncio.wait_for(
            self._snapshot_impl(allow_recovering=allow_recovering),
            timeout=protocol_timeout,
        )

    async def _snapshot_impl(self, *, allow_recovering: bool = False) -> ChatSnapshot:
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
        observed_binding = (
            self._page_generation, self.page_handle, self.target_id,
            self.provider_session_id, canonical_chat_url(self.chat_url or ""),
        )
        page = await self._gpt_browser().page_by_handle(str(observed_binding[1]))
        target_id = str(getattr(page, "target_id", "") or "")
        if target_id:
            self.target_id = target_id
        budget_observed = (self._conversation_load_recovery_attempts, self._conversation_load_recovery_revision)
        snapshot = ChatSnapshot.from_bridge(
            await self._gpt_browser().snapshot(page, signals=self.config.workflow.bridge_signals())
        )
        self._last_url = snapshot.url
        self._last_snapshot = snapshot
        self._load_budget_observation = (snapshot, budget_observed, observed_binding)
        remember = getattr(self.runtime, "remember_tab_activity", None)
        if callable(remember) and not self._replacement_target_pending:
            remember(self)
        # Capture labels during recovery/baseline observations too, not only
        # the normal response loop. Never relay a label from a different tab.
        if not self._replacement_target_pending and snapshot.conversation_title and (
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
        # A few lightweight adapter doubles are constructed with
        # ``object.__new__``; retain the production lock invariant while
        # keeping those observation-only seams safe.
        lock = getattr(self, "_page_mutation_lock", None)
        if lock is None:
            lock = self._page_mutation_lock = asyncio.Lock()
        async with lock:
            if not self.page_handle or not self._page_mutation_owner_is_live():
                return False
            browser = self._gpt_browser()
            retry = getattr(browser, "retry_delivery_timeout", None)
            if not callable(retry):
                return False
            page = await browser.page_by_handle(self.page_handle)
            if not self._page_mutation_owner_is_live():
                return False
            return bool(await retry(page))

    async def retry_conversation_load(self) -> bool:
        """Retry a load error or reload a native network page; never Send."""
        lock = getattr(self, "_page_mutation_lock", None)
        if lock is None:
            lock = self._page_mutation_lock = asyncio.Lock()
        async with lock:
            if not self.page_handle or not self._page_mutation_owner_is_live():
                return False
            browser = self._gpt_browser()
            retry = getattr(browser, "retry_conversation_load", None)
            if not callable(retry):
                return False
            page = await browser.page_by_handle(self.page_handle)
            expected_path = urlsplit(self.chat_url or "").path.rstrip("/") or None
            # Do not catch TypeError here. An internal provider/CDP TypeError must
            # remain visible; retrying without expected_path would bypass the
            # same-evaluation conversation identity fence after page reuse.
            if not self._page_mutation_owner_is_live():
                return False
            return bool(await retry(page, expected_path=expected_path))

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
        # A completed turn publishes its terminal evidence after the durable
        # checkpoint clear.  If a later metadata relay left the old unresolved
        # marker behind, that durable proof is stronger than another DOM poll:
        # keep the successor from retrying forever against an already-cleared
        # predecessor.
        if _terminal_evidence_proves_checkpoint_clear(
            self._checkpoint_metadata,
            unresolved_turn_id=self._checkpoint_metadata.get("unresolved-turn-id"),
        ):
            await self.persist_unresolved_clear()
            self.clear_unresolved_turn()
            self._set_unresolved_recovery("stale-unresolved-marker-cleared")
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
        # See turn.py's mirrored delivery_timeout_signal_now: two independent
        # detections of the same recovery opportunity, either sufficient.
        delivery_timeout_signal = (
            "delivery-timeout-retry" in snapshot.dom_signals
            or "delivery-timeout-alert" in snapshot.dom_signals
        )
        if (
            delivery_timeout_signal
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
                try:
                    retried = await self.retry_delivery_timeout()
                except Exception as exc:  # noqa: BLE001 - preserve recovery evidence
                    self._set_unresolved_recovery(
                        "delivery-timeout-retry-failed",
                        exception_type=type(exc).__name__,
                        exception=str(exc),
                    )
                    return False
                # Only consume the one-shot attempt on an actual click. A
                # signal that fired without a matching button has caused no
                # page side effect, so a later reconciliation pass must
                # still be allowed to retry once a real control is present.
                if retried:
                    self._reconciliation_delivery_retry_attempted = True
                    await asyncio.sleep(self.config.turn.poll_interval_seconds)
                    snapshot = await self.snapshot(allow_recovering=True)
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
            "submission-proven": self._submission_proven,
        }
        if self.target_id:
            values["target-id"] = self.target_id
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

    def terminal_checkpoint_metadata(self, turn_id: str) -> dict[str, object]:
        """Return private checkpoint proof for gateway-owned finalization only.

        These values are deliberately not part of SessionTurnResult.metadata:
        they contain provider message identity and a prompt fingerprint. The
        gateway uses this envelope to compare-and-clear the same durable turn.
        """
        if not isinstance(turn_id, str) or not turn_id:
            return {}
        retained = self._terminal_checkpoint_finalization
        if retained.get("unresolved-turn-id") == turn_id:
            return copy.deepcopy(retained)
        if (
            self._checkpoint_metadata.get("unresolved-turn-id") != turn_id
            or not self.unresolved_turn_pending
        ):
            return {}
        return self._private_terminal_checkpoint_projection()

    def capture_terminal_checkpoint_metadata(self, turn_id: str) -> dict[str, object]:
        """Retain the exact private checkpoint before provider-local clear.

        The provider turn clears its live recovery state after terminal DOM
        proof, while the gateway still has to durably finalize the request
        and session. Keep one turn-scoped copy across that boundary; the
        gateway acknowledges and releases it only after its compare-and-clear
        succeeds.
        """
        if (
            not isinstance(turn_id, str)
            or not turn_id
            or self._checkpoint_metadata.get("unresolved-turn-id") != turn_id
            or not self.unresolved_turn_pending
            or not self._submission_proven
        ):
            return {}
        self._terminal_checkpoint_finalization = (
            self._private_terminal_checkpoint_projection()
        )
        return copy.deepcopy(self._terminal_checkpoint_finalization)

    def _private_terminal_checkpoint_projection(self) -> dict[str, object]:
        # Some frozen identity fields are represented by dedicated in-memory
        # attributes rather than _checkpoint_metadata (notably prompt-text-
        # digest and submission-proven). Build from the complete private
        # projection, then allowlist the fields required by the gateway CAS.
        # Copy nested baseline data so a finalizer cannot mutate live state.
        private_projection = self.unresolved_metadata()
        return {
            key: copy.deepcopy(private_projection[key])
            for key in _TERMINAL_CHECKPOINT_METADATA_KEYS
            if key in private_projection
        }

    def mark_submission_unresolved(self, prompt_text: str | None = None) -> None:
        """Record that a send command completed but its provider identity is unknown."""
        self.unresolved_turn_pending = True
        self._submission_proven = False
        # A reusable session may carry the previous turn's durable identity.
        # Clear it before writing this turn's pre-send fence; omission alone
        # cannot remove merge-persisted predecessor metadata.
        self.unresolved_prompt_message_id = None
        self.unresolved_assistant_message_id = None
        self.unresolved_assistant_before_id = None
        self.unresolved_prompt_text_digest = None
        self._unresolved_recovery_reason = None
        self._unresolved_recovery_details = {}
        self._checkpoint_metadata = {}
        self._terminal_checkpoint_finalization = {}
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
        self._submission_proven = True
        self._checkpoint_metadata.update(
            {
                "recovery-state": "submission-proven",
                "submission-state": "proven",
                "submission-proof-source": "provider-user-message",
            }
        )
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

    def acknowledge_terminal_checkpoint_finalization(
        self,
        *,
        turn_id: str,
        terminal_metadata: dict[str, object],
        persisted_session_metadata: dict[str, object],
    ) -> bool:
        """Clear live recovery state after the gateway durably finalized a turn.

        The provider cannot clear its checkpoint while its request is still
        running. The gateway therefore owns the terminal write and invokes
        this acknowledgement only after its session record confirms that the
        exact request's terminal evidence cleared the durable fence.
        """
        evidence = terminal_metadata.get("terminal-evidence")
        observed = evidence.get("verification-evidence") if isinstance(evidence, dict) else None
        observed_set = set(observed) if isinstance(observed, (list, tuple, set)) else set()
        checkpoint = self._terminal_checkpoint_finalization
        checkpoint_turn_id = checkpoint.get("unresolved-turn-id")
        identity_keys = (
            "unresolved-turn-id",
            "submission-attempt-id",
            "submission-recovery-generation",
            "submission-recovery-claim",
            "unresolved-baseline-user-id",
            "unresolved-baseline-assistant-id",
            "unresolved-baseline-user-count",
            "unresolved-baseline-assistant-count",
            "unresolved-baseline-error-alert-occurrences",
            "prompt-text-digest",
        )
        identity_matches = all(
            (key in terminal_metadata) == (key in checkpoint)
            and (
                key not in checkpoint
                or terminal_metadata.get(key) == checkpoint.get(key)
            )
            for key in identity_keys
        )
        if not (
            isinstance(turn_id, str)
            and turn_id
            and checkpoint.get("unresolved-turn-pending") is True
            and checkpoint_turn_id == turn_id
            and isinstance(evidence, dict)
            and evidence.get("turn-id") == turn_id
            and evidence.get("policy") == "response-complete"
            and terminal_metadata.get("submission-proven") is True
            and terminal_metadata.get("submission-proof-source")
            == "provider-user-message"
            and identity_matches
            and {"not-generating", "text-present"}.issubset(observed_set)
            and observed_set.intersection({"completion-control", "response-complete-status"})
            and persisted_session_metadata.get("unresolved-turn-pending") is False
            and not persisted_session_metadata.get("unresolved-turn-id")
        ):
            return False

        self.clear_unresolved_turn()
        self._checkpoint_metadata = {}
        self._submission_proven = False
        self._terminal_checkpoint_finalization = {}
        if self.state is ChatState.RECOVERING and self.page_handle:
            self._move(ChatState.READY)
        return True

    def synchronize_cleared_predecessor_checkpoint(
        self, predecessor_id: str, expected_metadata: dict[str, object],
        persisted_session_metadata: dict[str, object],
    ) -> bool:
        """Mirror a gateway-verified terminal predecessor clear in idle memory.

        The gateway has verified the terminal artifact and compared/cleared
        this exact durable checkpoint. This only releases the matching local
        fence; it never upgrades submission proof or writes a checkpoint.
        """
        current = self._private_terminal_checkpoint_projection()
        identity_keys = _TERMINAL_CHECKPOINT_METADATA_KEYS - {"recovery-state"}
        if (
            self.state in {ChatState.READY, ChatState.RECOVERING}
            and not self.active_turn_id
            and not self.unresolved_turn_pending
            and not self._submission_proven
            and not current.get("unresolved-turn-id")
            and expected_metadata.get("unresolved-turn-id") == predecessor_id
            and expected_metadata.get("submission-attempt-id")
            and expected_metadata.get("prompt-text-digest")
            and persisted_session_metadata.get("unresolved-turn-pending") is False
            and not persisted_session_metadata.get("unresolved-turn-id")
            and same_chat_identity(self.chat_url or "", str(persisted_session_metadata.get("chat-url") or ""))
        ):
            # The exact clear already reached idle memory before a crash or
            # duplicate acknowledgment. No mutation is needed to retire its marker.
            return True
        if (
            self.state not in {ChatState.READY, ChatState.RECOVERING}
            or current.get("unresolved-turn-id") != predecessor_id
            or expected_metadata.get("unresolved-turn-id") != predecessor_id
            or not expected_metadata.get("submission-attempt-id")
            or not expected_metadata.get("prompt-text-digest")
            or persisted_session_metadata.get("unresolved-turn-pending") is not False
            or persisted_session_metadata.get("unresolved-turn-id")
            or not same_chat_identity(self.chat_url or "", str(persisted_session_metadata.get("chat-url") or ""))
            or any(
                (key in current) != (key in expected_metadata)
                or current.get(key) != expected_metadata.get(key)
                for key in identity_keys
            )
        ):
            return False
        self.clear_unresolved_turn()
        self._checkpoint_metadata = {}
        self._terminal_checkpoint_finalization = {}
        self._submission_proven = False
        if self.state is ChatState.RECOVERING and self.page_handle:
            self._move(ChatState.READY)
        return True

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
            if not self._page_mutation_owner_is_live():
                self._set_unresolved_recovery(
                    "refresh-owner-not-live",
                    request_id=request_id,
                    trigger=trigger,
                )
                return False
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
                raise ProviderBindingIntegrityError("page binding changed before response recovery")
            browser = self._gpt_browser()
            try:
                page = await browser.page_by_handle(handle)
                current_target = str(getattr(page, "target_id", "") or "")
                if self.target_id and current_target and current_target != self.target_id:
                    raise ProviderBindingIntegrityError("bound page target changed before refresh")
                current_url = str(getattr(page, "url", "") or "")
                if not current_url and hasattr(browser, "snapshot"):
                    observed = ChatSnapshot.from_bridge(
                        await browser.snapshot(
                            page,
                            signals=self.config.workflow.bridge_signals(),
                        )
                    )
                    current_url = observed.url
                if current_url and not same_chat_identity(current_url, bound_url):
                    raise ProviderBindingIntegrityError("bound page conversation URL changed before refresh")
                if not current_url or not url_matches_provider_session(
                    current_url, self.provider_session_id
                ):
                    raise ProviderBindingIntegrityError("bound page provider session changed before refresh")
                if not self._page_mutation_owner_is_live():
                    self._set_unresolved_recovery(
                        "refresh-owner-not-live",
                        request_id=request_id,
                        trigger=trigger,
                    )
                    return False
                # Refresh the observed route after validating stable identity;
                # a saved slugless route need not be directly navigable.
                await browser.navigate(page, canonical_chat_url(current_url) or bound_url)
                await asyncio.sleep(self.config.turn.poll_interval_seconds)
                if handle != self.page_handle:
                    raise ProviderBindingIntegrityError("bound page handle changed during refresh")
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
                    raise ProviderBindingIntegrityError("bound page target changed after refresh")
                if (
                    not refreshed_url
                    or not same_chat_identity(refreshed_url, bound_url)
                    or not url_matches_provider_session(
                        refreshed_url, self.provider_session_id
                    )
                ):
                    raise ProviderBindingIntegrityError("refresh left the bound conversation URL")
                logger.info(
                    "gpt-auto refreshed bound conversation trigger=%s request_id=%s",
                    trigger,
                    request_id,
                )
                return True
            except ProviderBindingIntegrityError as exc:
                self._set_unresolved_recovery(
                    "provider-binding-invalid",
                    request_id=request_id,
                    trigger=trigger,
                    exception_type=type(exc).__name__,
                    exception=str(exc),
                )
                raise
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
        bridge = getattr(self.runtime, "bridge", None)
        if bridge is None:
            return
        browser = self._gpt_browser()
        pages = await bridge.call("list_pages")
        if not isinstance(pages, list):
            return
        owners = getattr(self.runtime, "_page_owners", {})
        candidates: list[tuple[tuple[int, int], dict, ChatSnapshot]] = []
        for record in pages:
            handle = str(record.get("pageHandle") or "")
            if (
                not handle
                or not url_matches_provider_session(
                    str(record.get("url") or ""), self.provider_session_id
                )
                or (
                    isinstance(owners, dict)
                    and owners.get(handle) not in (None, self.ag_session_id)
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
            if "conversation-load-failed" in snapshot.dom_signals:
                continue
            candidates.append(((snapshot.user_count, snapshot.assistant_count), record, snapshot))
        if not candidates:
            return

        # Runtime lookup may have selected a healthy durable target in a prior
        # browser window. Do not let this second-stage DOM richness pass hop
        # back to a managed-window duplicate (or away from the current healthy
        # binding) after restart.
        for _score, record, snapshot in candidates:
            if (
                self.target_id
                and str(record.get("targetId") or "") == self.target_id
                and _snapshot_has_positive_conversation_evidence(snapshot)
            ):
                best_handle = str(record["pageHandle"])
                if best_handle == self.page_handle:
                    self._last_snapshot = snapshot
                    self._last_url = snapshot.url
                    return
                if not self._claim_page(best_handle):
                    continue
                old_handle = self.page_handle
                self._bind_page(record)
                if old_handle:
                    self.runtime.release_page(self, old_handle)
                self._last_snapshot = snapshot
                self._last_url = snapshot.url
                return

        positive = [
            item
            for item in candidates
            if _snapshot_has_positive_conversation_evidence(item[2])
        ]
        # Never mutate the binding to a merely non-error or blank duplicate.
        # A failed retained page remains the only safe Retry target until a
        # candidate proves the exact durable conversation is mounted.
        if not positive:
            return
        candidates = positive
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
                # The SPA can publish /c/<id> before adding its project route.
                # No further side effect is permitted here: wait within the
                # existing identity-acquisition deadline, never accept the bare
                # route or resend the already-submitted prompt.
                if expected_project_id and observed_project_id is None:
                    snap = None
                    await asyncio.sleep(0.2)
                    continue
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
        if self._physical_idle_closed:
            # An intentional inactivity close is not a CDP failure to heal.
            return
        if handle != self.page_handle or self.state is ChatState.CLOSED:
            return
        self.page_handle = None
        self._page_generation += 1
        self.runtime.release_page(self, handle)
        self._lost_during_turn = self.active_turn_id is not None
        if self._turn_requires_recovery_proof():
            # A provider load-error tab that an operator closes is not an
            # invitation to open another exact-URL tab.  Preserve the
            # unresolved fence so the next recovery/open attempt pauses until
            # an explicit dashboard reattach supplies the exact conversation.
            self._defer_page_creation_on_recovery = True
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
        except asyncio.CancelledError:
            raise
        except Exception:
            # Target loss commonly precedes the shared socket-loss event.
            # Retain the owned checkpoint for that coordinator, not FAILED.
            logger.info("gpt-auto page lost; awaiting conversation reconciliation", exc_info=True)

    async def retain_after_turn_failure(self, error: BaseException) -> bool:
        """Return to READY when a failed turn left this browser chat usable.

        A turn proof/response failure is not equivalent to browser or session
        destruction.  Keep the durable ChatGPT conversation bound so the
        gateway can resume it, while still using the chat transition engine to
        validate every recovery edge.  Unknown failures remain terminal.
        """
        if not _recoverable_turn_failure(error) or self.state is ChatState.CLOSED:
            return False
        details = error.details if isinstance(error, AudiaGenticError) else {}
        if (
            self.state is ChatState.RECOVERING
            and isinstance(error, AudiaGenticError)
            and error.code == "EXT-GPTAUTO-004"
            and isinstance(details, dict)
            and details.get("failure-stage") == "readiness"
            and details.get("submission-state") == "not_started"
            and details.get("submission-attempted") is False
            and details.get("submission-proven") is False
            and details.get("submission-ambiguous") is False
            and details.get("previous-turn-unresolved") is False
            and not self._turn_requires_recovery_proof()
            and url_matches_provider_session(self.chat_url or "", self.provider_session_id)
            and self._page_mutation_owner_is_live()
            and details.get("cause-type") != "ProviderBindingIntegrityError"
            and self._unresolved_recovery_reason not in {
                "provider-binding-invalid", "provider-conversation-not-found",
            }
            and not (
                self._last_snapshot is not None
                and "auth-required" in self._last_snapshot.dom_signals
            )
        ):
            # A missing/unready renderer does not invalidate its saved GPT
            # conversation. Keep admission closed in RECOVERING and let the
            # existing queue retry readiness under its outer deadline. This
            # path neither promotes READY nor replays a possibly sent turn.
            return True
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
        request_error_alert = "request-error-alert" in evidence
        if not evidence.intersection(
            {"error-page", "error-alert", "request-error-alert", "stream-cache-expired"}
        ):
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
                or (
                    not request_error_alert
                    and not (
                        snapshot.error_present
                        or snapshot.dom_signals.intersection(
                            {
                                "error-page",
                                "error-alert",
                                "request-error-alert",
                                "stream-cache-expired",
                            }
                        )
                    )
                )
                or snapshot.dom_signals.intersection(busy_signals)
            ):
                return False
            if not _terminal_error_request_owned(self, snapshot):
                return False
            stable_snapshot = snapshot
            if request_error_alert:
                # The correlated terminal decision is authoritative; the
                # provider may remove its transient alert before cleanup.
                stable_snapshot = replace(
                    snapshot,
                    dom_signals=frozenset(
                        signal
                        for signal in snapshot.dom_signals
                        if signal not in {"error-alert", "request-error-alert"}
                    ),
                    error_alert_occurrences=(),
                )
            if stable is not None and not request_error_alert and stable_snapshot != stable:
                return False
            if binding_token is None:
                binding_token = self._binding_token(snapshot)
            stable = stable_snapshot
            await asyncio.sleep(self.config.turn.response_stability_seconds)
        if binding_token is None or not await self._binding_token_is_current(binding_token):
            return False
        await self.persist_unresolved_clear()
        self.clear_unresolved_turn()
        self._reconciled_binding_token = binding_token
        self._set_unresolved_recovery(
            "request-owned-provider-error-released",
            evidence=sorted(
                evidence.intersection(
                    {
                        "error-page",
                        "error-alert",
                        "request-error-alert",
                        "stream-cache-expired",
                    }
                )
            ),
        )
        return True

    def bridge_replaced(self) -> None:
        """Invalidate bridge-local binding before runtime-level recovery."""
        if self.state is ChatState.CLOSED:
            return
        if self.page_handle is not None:
            self._page_generation += 1
        self.page_handle = None
        self._browser_generation_recovery = True
        if self.state is not ChatState.RECOVERING:
            self._move(ChatState.RECOVERING)

    def mark_recovery_failed(self) -> None:
        """Terminalize an isolated recovery failure through the chat graph."""
        if self.state is ChatState.RECOVERING:
            self._move(ChatState.FAILED)

    async def reconcile(self, pages: list[dict]) -> None:
        # Event recovery, admission and response observation may all notice a
        # lost target. Only one actor may rebind/reopen this conversation.
        async with self._reconcile_lock:
            await self._reconcile_page(pages)

    async def _adopt_recovery_page(self, page: dict) -> bool:
        """Rebind a physical tab only after reobserving the owned prompt."""
        if not self._page_mutation_owner_is_live():
            return False
        expected_url = self.chat_url or ""
        if not same_chat_identity(str(page.get("url") or ""), expected_url):
            return False
        handle = str(page.get("pageHandle") or "")
        previous = (self.page_handle, self.target_id, self._page_generation)
        previous_observation = (self._last_snapshot, self._last_url, self._load_budget_observation)
        if not self._claim_page(handle):
            return False
        self._replacement_target_pending = True
        self._bind_page(page)
        adopted = False
        try:
            adopted = await self._prove_recovery_page(expected_url)
            return adopted
        finally:
            release = getattr(self.runtime, "release_page", None)
            if adopted and callable(release) and handle != previous[0]:
                release(self, previous[0])
            if not adopted:
                if callable(release) and handle != previous[0]:
                    release(self, handle)
                self.page_handle, self.target_id, self._page_generation = previous
                self._last_snapshot, self._last_url, self._load_budget_observation = previous_observation
                self._replacement_target_pending = False

    async def _prove_recovery_page(self, expected_url: str) -> bool:
        snapshot = await self.snapshot(allow_recovering=True)
        if (
            not self._page_mutation_owner_is_live()
            or not same_chat_identity(snapshot.url, expected_url)
            or snapshot.error_present
            or "auth-required" in snapshot.dom_signals
            or not _unresolved_prompt_match_diagnostics(self, snapshot)[0]
        ):
            self._set_unresolved_recovery("replacement-target-turn-not-proven")
            self._move(ChatState.RECOVERING)
            return False
        update = self.binding_sink(ProviderSessionBindingUpdate(
            provider_session_ref=ProviderSessionRef(self.provider_session_id),
            metadata={"chat-url": self.chat_url, "target-id": self.target_id},
        ))
        if asyncio.iscoroutine(update):
            await update
        if not self._page_mutation_owner_is_live():
            raise ProviderBindingIntegrityError("recovery owner expired during binding persistence")
        self._replacement_target_pending = False
        self._browser_generation_recovery = False
        if self.active_turn_id:
            self._move(ChatState.BUSY)
        elif getattr(self, "_restart_recovery_pending", False):
            self._move(ChatState.READY)
        return True

    async def _rank_recovery_pages(self, pages: list[dict]) -> list[dict]:
        """Prefer an owned completed reply over a stale duplicate renderer."""
        ranked = []
        browser = self._gpt_browser()
        for index, page in enumerate(pages):
            rank = -1
            try:
                ref = await browser.page_by_handle(str(page["pageHandle"]))
                snapshot = ChatSnapshot.from_bridge(await asyncio.wait_for(
                    browser.snapshot(ref, signals=self.config.workflow.bridge_signals()),
                    timeout=self.config.cdp.protocol_timeout_seconds,
                ))
                if same_chat_identity(snapshot.url, self.chat_url or "") and _unresolved_prompt_match_diagnostics(self, snapshot)[0]:
                    terminal = (
                        not snapshot.generating and not snapshot.error_present
                        and snapshot.latest_assistant_id
                        and snapshot.terminal_witness_assistant_id == snapshot.latest_assistant_id
                        and snapshot.dom_signals.intersection({"completion-control", "response-complete-status"})
                    )
                    rank = 2 if terminal else int(snapshot.generating)
            except Exception:
                pass  # Candidate proof is retried by adoption/coordinator.
            ranked.append((rank, -index, page))
        return [page for _, _, page in sorted(ranked, key=lambda row: row[:2], reverse=True)]

    async def _reconcile_page(self, pages: list[dict]) -> None:
        if self._physical_idle_closed:
            return
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
            if (
                page is not None
                and self._turn_requires_recovery_proof()
                and (
                    (bool(self.target_id) and str(page.get("targetId") or "") != self.target_id)
                    or self._replacement_target_pending
                    or self._browser_generation_recovery
                    or getattr(self, "_restart_recovery_pending", False)
                    or sum(same_chat_identity(str(p.get("url") or ""), self.chat_url or "") for p in pages) > 1
                )
            ):
                # A target id belongs to a browser generation, not the turn.
                # Reobserve the exact prompt before continuing read-only
                # observation. This path never sends a provider prompt.
                if (self.active_turn_id or getattr(self, "_restart_recovery_pending", False)) and self._page_mutation_owner_is_live():
                    candidates = [page] + [p for p in pages if p.get("pageHandle") != page.get("pageHandle") and same_chat_identity(str(p.get("url") or ""), self.chat_url or "")]
                    if len(candidates) > 1:
                        candidates = await self._rank_recovery_pages(candidates)
                    for candidate in candidates:
                        try:
                            if await self._adopt_recovery_page(candidate):
                                return
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.debug("gpt-auto candidate proof pending", exc_info=True)
                    self._move(ChatState.RECOVERING)
                    return
                else:
                    self._set_unresolved_recovery("replacement-target-requires-owned-observer")
                    self._move(ChatState.RECOVERING)
                    return
            if page is None:
                page = await self._reopen_idle_conversation()
            if page is not None and self._claim_page(str(page["pageHandle"])):
                if not await self._recovery_page_is_current(page):
                    self.runtime.release_page(self, str(page["pageHandle"]))
                    self._move(ChatState.RECOVERING)
                    return
                self._bind_page(page)
                retained = await self._retained_page_snapshot()
                if not await self._replace_load_failed_page(retained):
                    await self._prefer_active_conversation_page()
                if self.active_turn_id:
                    self._move(ChatState.BUSY)
                else:
                    if self.unresolved_turn_pending and not await self._reconcile_unresolved_turn():
                        return
                    await self.wait_quiescent(allow_recovering=True)
                    if not await self._recovery_page_is_current(page):
                        self._move(ChatState.RECOVERING)
                        return
                    self._move(ChatState.READY)
                return
            if (
                self._defer_page_creation_on_recovery
                and self.provider_session_id
                and self._turn_requires_recovery_proof()
                and not self._browser_generation_recovery
            ):
                self._move(ChatState.RECOVERING)
                raise RuntimeError('gpt-auto restart recovery deferred: exact provider conversation tab is not attached')
            if not self.chat_url:
                self._set_unresolved_recovery(
                    "provider-conversation-not-found",
                    provider_session_id=self.provider_session_id,
                    reason="durable-chat-url-missing",
                )
                if self.state is ChatState.RECOVERING:
                    self._move(ChatState.FAILED)
                return
            if not self._page_mutation_owner_is_live():
                self._set_unresolved_recovery("reconcile-owner-not-live")
                return
            if self._turn_requires_recovery_proof():
                reopen = getattr(self.runtime, "reopen_conversation_page", None)
                if (self.active_turn_id or getattr(self, "_restart_recovery_pending", False)) and callable(reopen):
                    page = await reopen(self.chat_url, owner_is_live=self._page_mutation_owner_is_live)
                    await self._adopt_recovery_page(page)
                    return
                self._set_unresolved_recovery(
                    "conversation-load-observation-deferred",
                    provider_session_id=self.provider_session_id,
                    chat_url=self.chat_url,
                    defer_reason="exact-conversation-tab-detached",
                )
                # An unresolved Send is correlated only with the exact
                # provider conversation.  Reopening a fresh tab after an
                # operator closes the failed tab cannot prove that Send or
                # safely replay it, so pause and wait for explicit reattach.
                # In particular, do not turn a provider overload page into a
                # tab-creation loop or synthetic activity.
                self._move(ChatState.RECOVERING)
                return
            if self._conversation_load_recovery_exhausted():
                self._set_unresolved_recovery(
                    "conversation-load-recovery-backoff",
                    attempts=self._conversation_load_recovery_attempts,
                    provider_session_id=self.provider_session_id,
                    chat_url=self.chat_url,
                )
                # Do not manufacture synthetic activity for a page that is
                # not attached.  The request remains recoverable, but only a
                # later explicit reattach or the normal outer timeout may
                # change its state.
                self._move(ChatState.RECOVERING)
                return
            self.page_handle = await self._create_recovery_page()
            if not self.runtime.claim_page(self, self.page_handle):
                raise RuntimeError("gpt-auto created a page already owned by another session")
            try:
                if not self._page_mutation_owner_is_live():
                    raise ProviderBindingIntegrityError(
                        "gpt-auto recovery navigation refused without a live durable owner"
                    )
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
                if handle:
                    try:
                        await self.runtime.bridge.call(
                            "close_page", {"pageHandle": handle}
                        )
                    except Exception:
                        logger.debug(
                            "failed to close unowned gpt-auto recovery tab",
                            exc_info=True,
                        )
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
        if not self._page_mutation_owner_is_live():
            self._set_unresolved_recovery("reconcile-owner-not-live")
            return
        self.page_handle = await self._create_recovery_page()
        if not self._claim_page(self.page_handle):
            raise RuntimeError("gpt-auto created a page already owned by another session")
        if not self._page_mutation_owner_is_live():
            handle, self.page_handle = self.page_handle, None
            self.runtime.release_page(self, handle)
            if handle:
                try:
                    await self.runtime.bridge.call(
                        "close_page", {"pageHandle": handle}
                    )
                except Exception:
                    logger.debug(
                        "failed to close unowned gpt-auto recovery tab",
                        exc_info=True,
                    )
            self._set_unresolved_recovery("reconcile-owner-not-live")
            return
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
        runtime_config = getattr(self.runtime, "config", None)
        browser_config = getattr(runtime_config, "browser", None)
        # Small recovery/test runtimes may intentionally omit the full
        # provider config. Closing a failed open must still reach CLOSED and
        # unregister the chat; absence of an optional tab-retention setting
        # means retain the default behavior.
        close_on_session_close = bool(
            getattr(browser_config, "close_tabs_on_session_close", False)
        )
        if handle and not close_on_session_close:
            retain = getattr(self.runtime, "retain_detached_page", None)
            if callable(retain):
                try:
                    retain(
                        self,
                        handle,
                        self._last_validated_activity_monotonic,
                        protected=(self.active_turn_id is not None or self.unresolved_turn_pending),
                    )
                except TypeError:
                    # Preserve compatibility with lightweight runtime doubles.
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
    # A document-level role=alert can be stale from a prior turn. It is
    # diagnostic only; request-owned correlation is decided by the turn.
    failed_signals = {"auth-required", "error-page"}
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


def _terminal_evidence_proves_checkpoint_clear(
    metadata: dict[str, object], *, unresolved_turn_id: object
) -> bool:
    """Return whether provider terminal metadata proves the fence was cleared."""
    evidence = metadata.get("terminal-evidence")
    if not isinstance(evidence, dict):
        return False
    if not isinstance(unresolved_turn_id, str) or not unresolved_turn_id:
        return False
    if evidence.get("turn-id") != unresolved_turn_id:
        return False
    if evidence.get("checkpoint-clear-persisted") is not True:
        return False
    if evidence.get("policy") != "response-complete":
        return False
    observed = evidence.get("verification-evidence")
    if not isinstance(observed, (list, tuple, set)):
        return False
    observed_set = set(observed)
    return (
        {"not-generating", "text-present"} <= observed_set
        and bool(observed_set.intersection({"completion-control", "response-complete-status"}))
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
        failed_signals.update({"error-page"})
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


def _metadata_int(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


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
