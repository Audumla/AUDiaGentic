"""Small mapping-normalization primitives shared by agent gateway boundaries."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_GENERIC_CHAT_TITLES = frozenset({
    "skip to content",
    "chat history",
    "open sidebar",
    "close sidebar",
})


def first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Return the value for the first present key, preserving explicit ``None``."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def normalize_chat_title(value: Any) -> str | None:
    """Return a bounded conversation label, excluding navigation labels."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or text.casefold() in _GENERIC_CHAT_TITLES:
        return None
    return text[:256]


__all__ = ["first_present", "normalize_chat_title"]
