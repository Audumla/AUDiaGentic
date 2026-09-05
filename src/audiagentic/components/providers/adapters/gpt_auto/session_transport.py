"""Thin neutral transport façade over a shared-runtime PersistentChat."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
)
from audiagentic.foundation.transports.session_binding import ProviderSessionRef

from .chat import ChatState, PersistentChat
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

    @property
    def ag_session_id(self) -> str:
        return self.chat.ag_session_id

    async def open(self) -> SessionOpenResult:
        await self.chat.open()
        metadata: dict[str, Any] = {"project-url": self.chat.project_url}
        metadata.update(self.chat.unresolved_metadata())
        ref = None
        if self.chat.provider_session_id:
            ref = ProviderSessionRef(self.chat.provider_session_id)
            metadata.update(
                {
                    "provider-session-id": self.chat.provider_session_id,
                    "chat-url": self.chat.chat_url,
                }
            )
        return SessionOpenResult(
            ag_session_id=self.chat.ag_session_id,
            provider_session_ref=ref,
            metadata=metadata,
        )

    async def prompt(self, request: SessionPrompt, sink: ObservationSink) -> SessionTurnResult:
        if self._closed:
            raise RuntimeError("gpt-auto chat is not ready")
        # Admission can fail before a GptAutoTurn exists (for example an
        # unresolved prior send).  Route that failure through the same
        # provider recovery disposition as failures raised by turn.run();
        # otherwise the gateway would incorrectly terminate a still
        # recoverable conversation and every later prompt would get
        # RES-AGW-003.
        try:
            await self.chat.ensure_ready()
        except Exception as exc:
            retained = await self.chat.retain_after_turn_failure(exc)
            self._turn_failure_disposition = (
                SessionFailureDisposition.RETAIN
                if retained
                else SessionFailureDisposition.TERMINATE
            )
            raise
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

    async def control(self, request: SessionControlRequest) -> SessionControlResult:
        if request.action is SessionControlAction.CANCEL_TURN:
            if self._active_turn is None:
                return SessionControlResult(
                    ControlDisposition.ALREADY_TERMINAL, CorrelationQuality.REQUEST_SCOPED
                )
            if request.turn_id != self._active_turn.request.turn_id:
                return SessionControlResult(
                    ControlDisposition.ALREADY_TERMINAL, CorrelationQuality.REQUEST_SCOPED
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

    async def reconcile_activity_gap(self) -> dict[str, Any]:
        """Revalidate and, once, bump a quiet CDP conversation without resending."""
        if self._closed:
            return {"status": "unavailable", "reason": "transport-closed"}
        # First repair a recycled/closed page binding. Any resulting activity
        # is still observed by the normal turn relay and must renew the
        # gateway lease independently.
        await self.chat._validate_page_binding()
        # A request with no accepted activity has no provider lease to expire,
        # so the watchdog gives the retained page one bounded, read-only
        # refresh opportunity. _refresh_for_reconciliation() is fenced by the
        # chat object and can therefore never refresh repeatedly or submit a
        # second prompt.
        refreshed = False
        refresh = getattr(self.chat, "_refresh_for_reconciliation", None)
        if callable(refresh) and getattr(self.chat, "active_turn_id", None):
            refreshed = bool(await refresh())
        return {
            "status": "reconciled",
            "state": self.chat.state.value,
            "action": "page-refresh" if refreshed else "page-revalidated",
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
