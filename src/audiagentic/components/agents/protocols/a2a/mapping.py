"""Pure A2A-to-Agents mappings; no A2A SDK or persistence imports."""
from __future__ import annotations

from collections.abc import Mapping


def work_status(work: Mapping[str, object]) -> str:
    state = str(work.get("state"))
    return {"submitted": "submitted", "active": "working", "waiting": "input-required", "completed": "completed", "failed": "failed", "cancelled": "canceled", "rejected": "failed"}.get(state, "failed")


def text_message(message: Mapping[str, object]) -> str:
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("A2A requires a text message")
    texts = [part.get("text") for part in parts if isinstance(part, Mapping) and part.get("kind", "text") == "text"]
    if len(texts) != len(parts) or not texts:
        raise ValueError("unsupported rich A2A parts")
    return "\n".join(str(value) for value in texts)
