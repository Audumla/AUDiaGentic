"""Thin neutral transport façade over a shared-runtime PersistentChat."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway.session.client_defaults import (
    _bounded_cause_message,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import (
    ControlDisposition,
    CorrelationQuality,
    ObservationSink,
    SessionControlAction,
    SessionControlRequest,
    SessionControlResult,
    SessionFailureDisposition,
    SessionOpenResult,
    SessionPrompt,
    SessionTurnResult,
    TransportObservation,
    TransportObservationKind,
)
from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)

from .chat import ChatState, PersistentChat
from .cdp.client import CdpError
from .config import GptAutoConfig
from .runtime_registry import get_runtime
from .turn import GptAutoTurn
from .urls import (
    canonical_chat_url,
    parse_project_id,
    parse_provider_session_id,
    url_matches_provider_session,
)


class GptAutoSessionTransport:
    def __init__(self, chat: PersistentChat) -> None:
        self.chat = chat
        self._active_turn: GptAutoTurn | None = None
        self._closed = False
        self._turn_failure_disposition = SessionFailureDisposition.TERMINATE
        self._pending_cancel_turn_id: str | None = None

    @property
    def ag_session_id(self) -> str:
        return self.chat.ag_session_id

    def set_request_metadata_sink(self, sink: Any | None) -> None:
        """Route checkpoint metadata to the request owning the active turn."""
        self.chat.set_request_metadata_sink(sink)

    async def open(self) -> SessionOpenResult:
        await self.chat.open()
        metadata: dict[str, Any] = {"project-url": self.chat.project_url}
        metadata.update(self.chat.unresolved_metadata())
        ref = None
        if self.chat.provider_session_id:
            ref = ProviderSessionRef(self.chat.provider_session_id)
            binding_metadata = {
                "provider-session-id": self.chat.provider_session_id,
                "chat-url": self.chat.chat_url,
            }
            if self.chat.target_id:
                binding_metadata["target-id"] = self.chat.target_id
            metadata.update(binding_metadata)
            # Rehydration may have rebound to an exact-URL fallback target.
            # Refresh the immutable provider binding's scalar metadata without
            # changing its provider-session reference, so the next restart
            # prefers the newly proven physical target. This is observation
            # only; no prompt is sent from this path.
            result = self.chat.binding_sink(
                ProviderSessionBindingUpdate(
                    provider_session_ref=ref,
                    metadata=binding_metadata,
                )
            )
            if inspect.isawaitable(result):
                await result
        return SessionOpenResult(
            ag_session_id=self.chat.ag_session_id,
            provider_session_ref=ref,
            metadata=metadata,
        )

    async def prompt(self, request: SessionPrompt, sink: ObservationSink) -> SessionTurnResult:
        if self._closed:
            raise RuntimeError("gpt-auto chat is not ready")
        # Readiness and project admission can spend a long time in CDP/browser
        # work before GptAutoTurn has a DOM snapshot to compare.  Emit a
        # request-scoped provider observation before entering that path so the
        # durable gateway activity lease does not remain at sequence zero while
        # the provider adapter is actively inspecting the browser.
        await self._emit_activity(sink, request, "preflight-inspected")
        # Admission can fail before a GptAutoTurn exists (for example an
        # unresolved prior send).  Route that failure through the same
        # provider recovery disposition as failures raised by turn.run();
        # otherwise the gateway would incorrectly terminate a still
        # recoverable conversation and every later prompt would get
        # RES-AGW-003.
        try:
            await self.chat.ensure_ready()
            # A successful readiness pass is a second meaningful provider
            # observation even when the first post-submit DOM snapshot has not
            # materialized a new user/assistant node yet.
            await self._emit_activity(sink, request, "preflight-evaluated")
        except Exception as exc:
            metadata_fn = getattr(self.chat, "unresolved_metadata", None)
            metadata = metadata_fn() if callable(metadata_fn) else {}
            unresolved = bool(metadata.get("unresolved-turn-pending"))
            # Preserve the typed load-error evidence emitted by
            # PersistentChat.  The gateway's dispatch policy uses the
            # explicit unsent/ambiguous fields to decide whether a fresh
            # session replay is safe; wrapping this as generic EXT-004 would
            # erase that distinction and make the guarded recovery path
            # unreachable from normal prompt admission.
            if isinstance(exc, AudiaGenticError) and exc.code == "EXT-GPTAUTO-005":
                details = dict(exc.details or {})
                details.setdefault("failure-stage", "readiness")
                details.setdefault("submission-state", "not_started")
                details.setdefault("retryable-same-session", False)
                details.setdefault("previous-turn-unresolved", unresolved)
                details.setdefault("request-id", request.turn_id)
                details.setdefault("session-id", getattr(self.chat, "ag_session_id", None))
                failure = AudiaGenticError(
                    code=exc.code,
                    kind=exc.kind,
                    message=exc.message,
                    details=details,
                )
            else:
                failure = AudiaGenticError(
                    code="EXT-GPTAUTO-004",
                    kind="providers",
                    message="gpt-auto turn admission failed before provider submission",
                    details={
                        "failure-stage": "readiness",
                        "submission-state": "not_started",
                        "retryable-same-session": False,
                        "previous-turn-unresolved": unresolved,
                        "cause-type": type(exc).__name__,
                        "cause-message": _bounded_cause_message(exc),
                        "request-id": request.turn_id,
                        "session-id": getattr(self.chat, "ag_session_id", None),
                    },
                )
            retained = await self.chat.retain_after_turn_failure(failure)
            details = dict(failure.details or {})
            # A recovery helper may return True after it has performed best-
            # effort cleanup, but that does not mean the provider session is
            # still usable.  In particular, an unresolved turn on a session
            # that has already entered FAILED/CLOSED must not keep the
            # gateway request in an endless recovery retry loop.
            post_retain_metadata_fn = getattr(self.chat, "unresolved_metadata", None)
            post_retain_metadata = (
                post_retain_metadata_fn() if callable(post_retain_metadata_fn) else {}
            )
            post_retain_unresolved = bool(
                post_retain_metadata.get("unresolved-turn-pending")
            )
            session_state = getattr(self.chat, "state", None)
            session_usable = session_state not in {ChatState.FAILED, ChatState.CLOSED}
            details["retryable-same-session"] = bool(
                retained
                and not post_retain_unresolved
                and session_usable
            )
            failure = AudiaGenticError(
                code=failure.code,
                kind=failure.kind,
                message=failure.message,
                details=details,
            )
            self._turn_failure_disposition = (
                SessionFailureDisposition.RETAIN
                if retained and session_usable
                else SessionFailureDisposition.TERMINATE
            )
            raise failure from exc
        self._turn_failure_disposition = SessionFailureDisposition.TERMINATE
        turn = GptAutoTurn(self.chat, request, sink)
        self._active_turn = turn
        try:
            return await turn.run()
        except Exception as exc:
            retained = await self.chat.retain_after_turn_failure(exc)
            self._turn_failure_disposition = (
                SessionFailureDisposition.RETAIN
                if retained
                else SessionFailureDisposition.TERMINATE
            )
            raise
        finally:
            self._active_turn = None

    async def _emit_activity(
        self,
        sink: ObservationSink,
        request: SessionPrompt,
        phase: str,
    ) -> None:
        """Relay bounded provider lifecycle activity without provider payloads."""
        mark_activity = getattr(self.chat, "mark_validated_activity", None)
        if callable(mark_activity) and phase not in {
            "connection-refreshing",
            "provider-busy",
            "response-observing",
            "recovery-observing",
            "preflight-inspected",
            "preflight-evaluated",
        }:
            mark_activity()
        observation = TransportObservation(
            ag_session_id=self.chat.ag_session_id,
            turn_id=request.turn_id,
            sequence=None,
            kind=TransportObservationKind.ACTIVITY,
            observed_at=now_iso_z(),
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes={"model_activity": phase},
        )
        result = sink(observation)
        if inspect.isawaitable(result):
            await result

    async def resume_existing(
        self, request: SessionPrompt, sink: ObservationSink
    ) -> SessionTurnResult:
        """Observe the request-owned turn after a gateway generation handoff.

        This path is intentionally separate from ``prompt``: the durable
        unresolved checkpoint proves that a provider side effect may already
        exist, so recovery must never call the composer or submit a prompt.
        """
        if self._closed:
            raise RuntimeError("gpt-auto chat is not ready")
        # Recovery can spend the same long interval rehydrating/revalidating
        # the CDP page. Keep the request-owned activity lease honest on this
        # path as well; the resumed turn will emit its sequenced observations
        # once its provider snapshot loop is active.
        # This is only a recovery-attempt marker.  It is deliberately not
        # provider progress: an unchanged DOM inspected by a reconstructed
        # observer must not renew the request lease or reset recovery bounds.
        await self._emit_activity(sink, request, "recovery-observing")
        metadata = self.chat.unresolved_metadata()
        if not metadata.get("unresolved-turn-pending"):
            raise AudiaGenticError(
                "CON-AGW-124",
                "agents",
                "gpt-auto cannot prove a stale provider-session turn was unsent",
                {"failure-reason": "unresolved-checkpoint-unavailable"},
            )
        if metadata.get("unresolved-turn-id") != request.turn_id:
            raise RuntimeError(
                "gpt-auto unresolved turn does not belong to the recovered request"
            )
        turn = GptAutoTurn(self.chat, request, sink)
        self._active_turn = turn
        if self._pending_cancel_turn_id == request.turn_id:
            self._pending_cancel_turn_id = None
            turn.cancel()
        try:
            return await turn.resume_existing()
        except Exception as exc:
            retained = await self.chat.retain_after_turn_failure(exc)
            details = getattr(exc, "details", {})
            definitively_failed = (
                retained
                and getattr(exc, "code", None) == "EXT-GPTAUTO-003"
                and isinstance(details, dict)
                and details.get("failure-reason") == "provider-failure-policy-matched"
                and not self.chat.unresolved_metadata().get("unresolved-turn-pending")
            )
            # A reconstructed observer can fail before it gets a typed
            # provider result (for example while ChatGPT still shows the
            # connection-interrupted banner).  If the durable unresolved
            # checkpoint and provider binding are still present, this is
            # recoverable observation loss, not proof that the session died.
            # Keep the session alive so the queue can reattach and observe the
            # same turn again; only a correlated provider rejection that also
            # cleared the checkpoint is terminal.
            unresolved = self.chat.unresolved_metadata()
            durable_observation_recovery = bool(
                isinstance(exc, CdpError)
                and not definitively_failed
                and unresolved.get("unresolved-turn-pending")
                and self.chat.provider_session_id
                and self.chat.state not in {ChatState.FAILED, ChatState.CLOSED}
            )
            self._turn_failure_disposition = (
                SessionFailureDisposition.TERMINAL_FAILED
                if definitively_failed
                else SessionFailureDisposition.RETAIN
                if retained or durable_observation_recovery
                else SessionFailureDisposition.TERMINATE
            )
            raise
        finally:
            self._active_turn = None

    def defer_unresolved_reconciliation(self) -> None:
        """Keep the durable checkpoint for ``resume_existing`` to consume."""
        self.chat.defer_unresolved_reconciliation()

    async def control(self, request: SessionControlRequest) -> SessionControlResult:
        if request.action is SessionControlAction.CANCEL_TURN:
            if self._active_turn is None:
                metadata = self.chat.unresolved_metadata()
                if (
                    metadata.get("unresolved-turn-pending")
                    and metadata.get("unresolved-turn-id") == request.turn_id
                ):
                    self._pending_cancel_turn_id = request.turn_id
                    return SessionControlResult(
                        ControlDisposition.ACCEPTED, CorrelationQuality.REQUEST_SCOPED
                    )
                return SessionControlResult(
                    ControlDisposition.UNCERTAIN, CorrelationQuality.UNCERTAIN
                )
            if request.turn_id != self._active_turn.request.turn_id:
                return SessionControlResult(
                    ControlDisposition.UNCERTAIN, CorrelationQuality.UNCERTAIN
                )
            self._active_turn.cancel()
            return SessionControlResult(
                ControlDisposition.ACCEPTED, CorrelationQuality.REQUEST_SCOPED
            )
        if request.action is SessionControlAction.CLOSE_SESSION:
            return SessionControlResult(
                ControlDisposition.UNSUPPORTED, CorrelationQuality.UNCERTAIN
            )
        return SessionControlResult(ControlDisposition.UNSUPPORTED, CorrelationQuality.UNCERTAIN)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Always release the PersistentChat/runtime ownership claim, even when
        # waiting for an in-flight turn raises a provider error.  Previously a
        # non-timeout wait failure skipped ``chat.close()`` and left the
        # conversation owned in the process, so every later BigCherry turn
        # failed with "conversation is already owned" until gateway restart.
        try:
            if self._active_turn:
                turn = self._active_turn
                turn.cancel()
                try:
                    await turn.wait_done(
                        timeout=max(
                            1.0,
                            self.chat.config.turn.submission_timeout_seconds
                            + self.chat.config.chat.ready_timeout_seconds
                            + 1.0,
                        )
                    )
                except TimeoutError:
                    # Detach is still safe because GPT-auto retains physical
                    # tabs by default; do not hold gateway shutdown
                    # indefinitely.
                    pass
        finally:
            await self.chat.close()

    def is_alive(self) -> bool:
        return not self._closed and self.chat.state not in {ChatState.FAILED, ChatState.CLOSED}

    def turn_failure_disposition(self) -> SessionFailureDisposition:
        return self._turn_failure_disposition

    def mark_turn_pending(self) -> None:
        """Keep the physical provider tab while this session turn waits FIFO."""
        self.chat.mark_turn_pending()

    def clear_turn_pending(self) -> None:
        """Release the physical-tab reaper guard after FIFO acquisition."""
        self.chat.clear_turn_pending()

    async def reconcile_activity_gap(self) -> dict[str, Any]:
        """Revalidate a quiet conversation without owning turn recovery."""
        if self._closed:
            return {"status": "unavailable", "reason": "transport-closed"}
        await self.chat._validate_page_binding()

        # Active-turn response recovery is owned exclusively by
        # GptAutoTurn._await_response(). The watchdog may repair/revalidate
        # page binding, but must not create a second refresh authority outside
        # the turn's spacing, attempt, and final-grace policy.
        return {
            "status": "reconciled",
            "state": self.chat.state.value,
            "action": "page-revalidated",
        }


def build_session_transport(
    project_root: Path,
    *,
    config: dict[str, Any],
    ag_session_id: str,
    binding_sink: Any,
    resume_provider_ref: str | None = None,
    resume_metadata_hint: dict[str, Any] | None = None,
    checkpoint_sink: Any | None = None,
    project_name: str,
) -> GptAutoSessionTransport:
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("gpt-auto session transport requires an admitted project name")
    parsed = GptAutoConfig.from_project_dict(config)
    runtime = get_runtime(project_root, parsed)
    metadata = resume_metadata_hint or {}
    project_url_value = metadata.get("project-url") or parsed.project_url
    project_url = str(project_url_value) if project_url_value else None
    chat_url = metadata.get("chat-url")
    if isinstance(chat_url, str) and chat_url:
        chat_url = canonical_chat_url(chat_url)
        if chat_url is None:
            raise RuntimeError(
                "gpt-auto resume requires a project-scoped durable chat-url"
            )
        parsed_ref = parse_provider_session_id(chat_url)
        if parsed_ref is None:
            raise RuntimeError("gpt-auto resume chat-url has no conversation id")
        if resume_provider_ref is None:
            resume_provider_ref = parsed_ref
        elif resume_provider_ref != parsed_ref:
            raise RuntimeError(
                "gpt-auto resume requires a matching project-scoped durable chat-url"
            )
        supplied_project = parse_project_id(chat_url)
        configured_project = parse_project_id(project_url or "")
        if configured_project and supplied_project != configured_project:
            raise RuntimeError(
                "gpt-auto resume chat-url belongs to a different configured project"
            )
        from .urls import canonical_project_url

        project_url = canonical_project_url(chat_url) + "/project"
    if resume_provider_ref:
        if isinstance(chat_url, str) and chat_url:
            if not url_matches_provider_session(chat_url, resume_provider_ref):
                raise RuntimeError(
                    "gpt-auto resume requires a matching project-scoped durable chat-url "
                    "and provider ref"
                )
            chat_url = canonical_chat_url(chat_url)
            if chat_url is None:
                raise RuntimeError(
                    "gpt-auto resume requires a project-scoped durable chat-url"
                )
        else:
            # A missing chat-url does not mean the conversation is lost --
            # PersistentChat.open()/reconcile() can still locate the live tab
            # by provider_session_id via find_conversation_page, or recreate
            # it once a URL is recovered from the provider.  Failing here
            # before that browser-based reconciliation runs turns transient
            # metadata staleness into a hard, unrecoverable resume failure.
            chat_url = None
    chat = PersistentChat(
        ag_session_id=ag_session_id,
        project_name=project_name.strip(),
        project_url=project_url,
        runtime=runtime,
        config=parsed,
        binding_sink=binding_sink,
        provider_session_id=resume_provider_ref,
        chat_url=chat_url,
        resume_provider_metadata=metadata,
        checkpoint_sink=checkpoint_sink,
        project_key=str(project_root.resolve()),
    )
    return GptAutoSessionTransport(chat)


__all__ = ["GptAutoSessionTransport", "build_session_transport"]
