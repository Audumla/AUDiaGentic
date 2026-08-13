"""Atomic ChatGPT page snapshot contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PageObservationState(StrEnum):
    """Derived browser evidence; not a replacement for lifecycle state."""

    UNKNOWN = "unknown"
    LOADING = "loading"
    READY = "ready"
    COMPOSER_UNAVAILABLE = "composer-unavailable"
    SUBMITTING = "submitting"
    GENERATING = "generating"
    AWAITING_COMPLETION = "awaiting-completion"
    COMPLETED = "completed"
    FAILED = "failed"
    AUTH_REQUIRED = "auth-required"


@dataclass(frozen=True)
class PageObservation:
    """Small, serializable evidence projection for dashboards and heuristics."""

    state: PageObservationState
    markers: frozenset[str]

    def as_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {"state": self.state.value}
        if self.markers:
            result["markers"] = tuple(sorted(self.markers))
        return result


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
    generating: bool = False
    latest_user_id: str | None = None

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
            generating=bool(value.get("generating")),
            latest_user_id=_text(value.get("latestUserId")),
        )

    def observe(
        self,
        *,
        baseline: "ChatSnapshot | None" = None,
        previous: "ChatSnapshot | None" = None,
    ) -> PageObservation:
        """Classify one atomic snapshot from explicit, bounded evidence."""
        baseline = baseline or self
        previous = previous or baseline
        signals = set(self.dom_signals)
        markers = set(signals)
        if self.url:
            markers.add("url-present")
        if self.composer_present:
            markers.add("composer-present")
        if self.composer_editable:
            markers.add("composer-editable")
        if self.composer_present and self.composer_editable:
            markers.add("composer-ready")
        if self.latest_assistant_text:
            markers.add("text-present")
        user_fresh = bool(
            self.latest_user_id and self.latest_user_id != baseline.latest_user_id
        ) or self.user_count > baseline.user_count
        assistant_fresh = bool(
            self.latest_assistant_id
            and self.latest_assistant_id != baseline.latest_assistant_id
        )
        text_changed = self.latest_assistant_text != previous.latest_assistant_text
        if user_fresh:
            markers.add("user-fresh")
        if assistant_fresh:
            markers.add("assistant-fresh")
        if text_changed and self.latest_assistant_text:
            markers.add("text-changed")
        auth_required = "auth-required" in signals
        error_visible = self.error_present or bool(
            signals.intersection({"error-page", "error-alert"})
        )
        busy = self.generating or bool(
            signals.intersection(
                {"stop-control", "streaming-indicator", "thinking-indicator", "busy-indicator"}
            )
        )
        completion_visible = "completion-control" in signals
        complete = (
            assistant_fresh
            and bool(self.latest_assistant_text)
            and completion_visible
            and not busy
        )
        if auth_required:
            state = PageObservationState.AUTH_REQUIRED
            markers.add("auth-required")
        elif error_visible:
            state = PageObservationState.FAILED
            markers.add("error-visible")
        elif not self.url or not self.composer_present:
            state = PageObservationState.LOADING
        elif complete:
            state = PageObservationState.COMPLETED
            markers.add("response-complete")
        elif busy:
            state = PageObservationState.GENERATING
            markers.add("response-active")
        elif user_fresh and not assistant_fresh:
            state = PageObservationState.SUBMITTING
            markers.add("prompt-observed")
        elif not self.composer_editable:
            state = PageObservationState.COMPOSER_UNAVAILABLE
        elif assistant_fresh and self.latest_assistant_text:
            state = PageObservationState.AWAITING_COMPLETION
            markers.add("response-observed")
        elif self.composer_editable:
            state = PageObservationState.READY
        else:
            state = PageObservationState.UNKNOWN
        if busy:
            markers.add("generation-active")
        if complete:
            markers.add("completion-visible")
        return PageObservation(state=state, markers=frozenset(markers))


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
