"""Atomic ChatGPT page snapshot contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from audiagentic.components.agents.gateway.mapping import normalize_chat_title


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
class ChatMessageRef:
    """One message in true DOM order, spanning both roles.

    GP08 slice 1: the per-role id/text arrays on ChatSnapshot cannot express
    cross-role interleaving order (whether a user message landed before or
    after a given assistant message within one poll) -- exactly what a
    request-scoped correlation boundary needs to know. This is the raw,
    ordered sequence those arrays are derived from.
    """

    role: str
    message_id: str | None
    text: str | None
    sequence: int
    # Provider-private correlation representation.  ChatGPT can render
    # structural Markdown (for example a thematic break) as an element that
    # contributes no innerText.  Keep that reconstruction separate from the
    # visible text used for diagnostics and display.
    correlation_text: str | None = None
    structural_hr_count: int = 0


_PROGRESS_KINDS = frozenset({
    "inspected",
    "fetching",
    "analyzing",
    "evaluated",
    "thinking",
    "called-tool",
    "talked-to-app",
    "searching-web",
    "read-resource",
})


@dataclass(frozen=True)
class ChatProgressBlock:
    """Safe, request-addressable projection of one visible progress block."""

    owner_prompt_message_id: str
    owner_assistant_message_id: str | None
    kind: str
    digest: str


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
    # Assistant message owning the structural completion controls. These
    # controls are otherwise conversation-global DOM evidence.
    terminal_witness_assistant_id: str | None = None
    # The bounded conversation label ChatGPT renders in the left navigation.
    # It is provider metadata, not response content; keeping it on the atomic
    # snapshot lets the gateway persist changes as soon as the label appears.
    conversation_title: str | None = None
    generating: bool = False
    latest_user_id: str | None = None
    user_message_ids: tuple[str, ...] = ()
    user_message_texts: tuple[str, ...] = ()
    # GP08: ordered assistant-message sequence, mirroring the user-message
    # arrays above -- the raw data a request-addressable correlation layer
    # needs. "Latest assistant" alone cannot answer "what was the response
    # to request A" once a later, unrelated turn has entered the
    # conversation.
    assistant_message_ids: tuple[str, ...] = ()
    assistant_message_texts: tuple[str, ...] = ()
    message_refs: tuple[ChatMessageRef, ...] = ()
    # Bounded, provider-neutral projection of visible tool/app affordances in
    # the current assistant turn. Values are counts by stable UI label (for
    # example ``called-tool`` or ``talked-to-app``), never tool arguments or
    # provider output. A changed count is verified evidence that the provider
    # is still working even when the assistant text is unchanged.
    tool_activity_counts: tuple[tuple[str, int], ...] = ()
    progress_blocks: tuple[ChatProgressBlock, ...] = ()

    @classmethod
    def from_bridge(cls, value: dict[str, Any]) -> ChatSnapshot:
        raw_tool_counts = value.get("toolActivityCounts") or {}
        if not isinstance(raw_tool_counts, dict):
            raw_tool_counts = {}
        return cls(
            url=str(value.get("url") or ""),
            conversation_title=_bounded_title(value.get("conversationTitle")),
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
            terminal_witness_assistant_id=_text(value.get("terminalWitnessAssistantId")),
            generating=bool(value.get("generating")),
            latest_user_id=_text(value.get("latestUserId")),
            user_message_ids=tuple(
                item.strip()
                for item in (value.get("userMessageIds") or ())
                if isinstance(item, str) and item.strip()
            ),
            user_message_texts=tuple(
                item.strip()
                for item in (value.get("userMessageTexts") or ())
                if isinstance(item, str) and item.strip()
            ),
            assistant_message_ids=tuple(
                item.strip()
                for item in (value.get("assistantMessageIds") or ())
                if isinstance(item, str) and item.strip()
            ),
            assistant_message_texts=tuple(
                item.strip()
                for item in (value.get("assistantMessageTexts") or ())
                if isinstance(item, str) and item.strip()
            ),
            message_refs=tuple(
                ChatMessageRef(
                    role=str(item.get("role") or ""),
                    message_id=_text(item.get("messageId")),
                    text=_text(item.get("text")),
                    sequence=int(item.get("sequence") or 0),
                    correlation_text=_text(item.get("correlationText")),
                    structural_hr_count=(
                        int(item.get("structuralHrCount") or 0)
                        if isinstance(item.get("structuralHrCount"), int)
                        and not isinstance(item.get("structuralHrCount"), bool)
                        else 0
                    ),
                )
                for item in (value.get("messageRefs") or ())
                if isinstance(item, dict)
            ),
            tool_activity_counts=tuple(
                sorted(
                    (
                        str(name),
                        int(count),
                    )
                    for name, count in raw_tool_counts.items()
                    if isinstance(name, str)
                    and isinstance(count, int)
                    and not isinstance(count, bool)
                    and count >= 0
                )
            ),
            progress_blocks=_progress_blocks(value.get("progressBlocks")),
        )

    def latest_user_ref(self) -> ChatMessageRef | None:
        """Return the latest user ref in the ordered DOM projection."""
        return next(
            (ref for ref in reversed(self.message_refs) if ref.role == "user"),
            None,
        )

    def latest_user_correlation_text(self) -> str | None:
        """Return structural correlation text, falling back to visible text."""
        ref = self.latest_user_ref()
        if ref is not None:
            return ref.correlation_text or ref.text
        return self.latest_user_text

    def user_prompt_refs(self) -> tuple[ChatMessageRef, ...]:
        """Return user refs with their provider-private correlation fallback."""
        return tuple(ref for ref in self.message_refs if ref.role == "user")

    def observe(
        self,
        *,
        baseline: ChatSnapshot | None = None,
        previous: ChatSnapshot | None = None,
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
        baseline_user_ids = set(baseline.user_message_ids)
        user_fresh = bool(
            self.latest_user_id
            and self.latest_user_id not in baseline_user_ids
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


def _bounded_token(value: Any, limit: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _progress_blocks(value: Any) -> tuple[ChatProgressBlock, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[ChatProgressBlock] = []
    for item in value[:128]:
        if not isinstance(item, dict):
            continue
        owner_prompt = _bounded_token(item.get("ownerPromptMessageId"))
        owner_assistant = _bounded_token(item.get("ownerAssistantMessageId"))
        kind = _bounded_token(item.get("kind"), 32)
        digest = _bounded_token(item.get("digest"), 16)
        if (
            not owner_prompt
            or kind not in _PROGRESS_KINDS
            or not digest
            or len(digest) != 16
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
        ):
            continue
        result.append(
            ChatProgressBlock(
                owner_prompt_message_id=owner_prompt,
                owner_assistant_message_id=owner_assistant,
                kind=kind,
                digest=digest.lower(),
            )
        )
    return tuple(result)


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _bounded_title(value: Any) -> str | None:
    return normalize_chat_title(value)
