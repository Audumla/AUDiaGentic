"""Provider-neutral contract for focusing an existing conversation tab."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ConversationFocusOutcome(StrEnum):
    FOCUSED = "focused"
    NOT_FOUND = "not-found"
    AMBIGUOUS = "ambiguous"
    IDENTITY_CONFLICT = "identity-conflict"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ConversationFocusLocator:
    """Durable identities only; CDP target/window handles are forbidden."""

    chat_url: str | None = None
    provider_session_id: str | None = None
    project_url: str | None = None
    # The gateway session id is a durable identity for the live runtime
    # fallback.  It is deliberately not a browser/CDP handle and is only
    # used when the provider has not published its conversation URL yet.
    gateway_session_id: str | None = None

    def to_mapping(self) -> dict[str, str | None]:
        result = {
            "chat-url": self.chat_url,
            "provider-session-id": self.provider_session_id,
            "project-url": self.project_url,
        }
        if self.gateway_session_id:
            result["gateway-session-id"] = self.gateway_session_id
        return result


@dataclass(frozen=True, slots=True)
class ConversationCaptureLocator(ConversationFocusLocator):
    """Private capture checkpoint when publication lost the conversation URL.

    The opaque provider target is only a candidate for observation, never a
    conversation identity. Adapters must reprove project, prompt and ordered
    turn ownership before returning output. Focus and serialized locators use
    only the inherited durable identities.
    """

    provider_target_id: str | None = field(default=None, repr=False)
    prompt_text_digest: str | None = field(default=None, repr=False)
    baseline_user_count: int | None = None
    baseline_assistant_count: int | None = None
    send_intent_ever: bool = False
    submission_stage: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationFocusResult:
    outcome: ConversationFocusOutcome
    reason: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {"outcome": self.outcome.value}
        if self.reason:
            result["reason"] = self.reason
        return result


__all__ = [
    "ConversationFocusLocator",
    "ConversationCaptureLocator",
    "ConversationFocusOutcome",
    "ConversationFocusResult",
]
