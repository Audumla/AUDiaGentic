"""Pure A2A-to-Agents mappings; no A2A SDK or persistence imports."""
from __future__ import annotations

from collections.abc import Mapping

#: Output text returned in a Task is bounded; the full output stays in the gateway output store.
MAX_OUTPUT_CHARS = 64_000

_TERMINAL = {"completed", "failed", "canceled", "rejected"}


def work_status(work: Mapping[str, object]) -> str:
    """Project a canonical Work state onto an A2A task state without inventing a result.

    Every Work state is mapped explicitly; an unrecognized state raises instead of being reported as a
    failure or a success the Work never had.
    """
    state = str(work.get("state"))
    if state == "waiting":
        reason = work.get("wait_reason")
        return {"user-input": "input-required", "approval": "input-required", "authentication": "auth-required"}.get(
            str(reason), "working")
    try:
        return {"submitted": "submitted", "active": "working", "completed": "completed", "failed": "failed",
                "cancelled": "canceled", "rejected": "rejected"}[state]
    except KeyError:
        raise ValueError(f"unrecognized Work state {state!r}") from None


def is_terminal(a2a_state: str) -> bool:
    return a2a_state in _TERMINAL


def text_message(message: Mapping[str, object]) -> str:
    """The text of a user message; every part must be plain text, anything richer is refused."""
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("A2A requires a text message")
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            raise ValueError("unsupported rich A2A parts")
        # Both `{"kind": "text", "text": ...}` and the bare `{"text": ...}` carry only a text field. Anything
        # that names another kind, or carries other content, is refused rather than flattened.
        if part.get("kind", "text") != "text" or set(part) - {"kind", "text", "metadata"}:
            raise ValueError("unsupported rich A2A parts")
        value = part.get("text")
        if not isinstance(value, str) or not value:
            raise ValueError("A2A text parts need non-empty text")
        texts.append(value)
    return "\n".join(texts)


def output_text(output: Mapping[str, object] | None) -> str:
    """Bounded plain text from a gateway output read, or empty when there is none."""
    if not isinstance(output, Mapping):
        return ""
    text = output.get("text")
    if isinstance(text, str):
        return text[:MAX_OUTPUT_CHARS]
    events = output.get("events")
    if isinstance(events, list):
        chunks = [str(event["text"]) for event in events if isinstance(event, Mapping) and isinstance(event.get("text"), str)]
        return "".join(chunks)[:MAX_OUTPUT_CHARS]
    return ""
