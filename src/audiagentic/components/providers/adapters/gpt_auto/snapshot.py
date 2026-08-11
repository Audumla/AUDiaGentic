"""Atomic ChatGPT page snapshot contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatSnapshot:
    url: str
    composer_present: bool
    composer_editable: bool
    user_count: int
    assistant_count: int
    latest_assistant_id: str | None
    latest_user_text: str | None
    latest_assistant_text: str | None
    dom_signals: frozenset[str]
    error_present: bool

    @classmethod
    def from_bridge(cls, value: dict[str, Any]) -> ChatSnapshot:
        return cls(
            url=str(value.get("url") or ""),
            composer_present=bool(value.get("composerPresent")),
            composer_editable=bool(value.get("composerEditable")),
            user_count=int(value.get("userCount") or 0),
            assistant_count=int(value.get("assistantCount") or 0),
            latest_assistant_id=_text(value.get("latestAssistantId")),
            latest_user_text=_text(value.get("latestUserText")),
            latest_assistant_text=_text(value.get("latestAssistantText")),
            dom_signals=frozenset(
                str(name)
                for name, present in (value.get("domSignals") or {}).items()
                if present
            ),
            error_present=bool(value.get("errorPresent")),
        )


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
