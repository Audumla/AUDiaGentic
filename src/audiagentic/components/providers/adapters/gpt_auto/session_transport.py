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
from .urls import canonical_chat_url, url_matches_provider_session


def _active_project_name(project_root: Path) -> str:
    from audiagentic.foundation.io import load_yaml_file

    config_path = project_root / ".audiagentic" / "config" / "project.yaml"
    if config_path.exists():
        data = load_yaml_file(config_path)
        if isinstance(data, dict):
            value = data.get("project-name", data.get("project_name"))
            if isinstance(value, str) and value.strip():
                return value.strip()
    return project_root.resolve().name


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
        if self._closed or self.chat.state is not ChatState.READY:
            raise RuntimeError("gpt-auto chat is not ready")
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
        if self._active_turn:
            self._active_turn.cancel()
        await self.chat.close()

    def is_alive(self) -> bool:
        return not self._closed and self.chat.state not in {ChatState.FAILED, ChatState.CLOSED}

    def turn_failure_disposition(self) -> SessionFailureDisposition:
        return self._turn_failure_disposition


def build_gpt_auto_session_transport(
    project_root: Path,
    *,
    config: dict[str, Any],
    ag_session_id: str,
    binding_sink: Any,
    resume_provider_ref: str | None = None,
    resume_metadata_hint: dict[str, Any] | None = None,
) -> GptAutoSessionTransport:
    parsed = GptAutoConfig.from_dict(config)
    runtime = get_runtime(project_root, parsed)
    metadata = resume_metadata_hint or {}
    project_url_value = metadata.get("project-url") or parsed.project_url
    project_url = str(project_url_value) if project_url_value else None
    chat_url = metadata.get("chat-url")
    if resume_provider_ref:
        if not isinstance(chat_url, str) or not url_matches_provider_session(
            chat_url, resume_provider_ref
        ):
            raise RuntimeError(
                "gpt-auto resume requires a matching durable chat-url and provider ref"
            )
        chat_url = canonical_chat_url(chat_url)
    chat = PersistentChat(
        ag_session_id=ag_session_id,
        project_name=_active_project_name(project_root),
        project_url=project_url,
        runtime=runtime,
        config=parsed,
        binding_sink=binding_sink,
        provider_session_id=resume_provider_ref,
        chat_url=chat_url,
    )
    return GptAutoSessionTransport(chat)


__all__ = ["GptAutoSessionTransport", "build_gpt_auto_session_transport"]
