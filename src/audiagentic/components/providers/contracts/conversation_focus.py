"""Provider-neutral contract for focusing an existing conversation tab."""

from __future__ import annotations

from dataclasses import dataclass
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

    def to_mapping(self) -> dict[str, str | None]:
        return {
            "chat-url": self.chat_url,
            "provider-session-id": self.provider_session_id,
            "project-url": self.project_url,
        }


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
    "ConversationFocusOutcome",
    "ConversationFocusResult",
]
