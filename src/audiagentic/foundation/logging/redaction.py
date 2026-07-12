"""Shared output redaction primitives.

Generalized from ``_RedactionFilter`` in ``foundation/logging/audit.py``.
Domain-neutral — safe to import from any layer without pulling in recipe or
component machinery.
"""
from __future__ import annotations

import re
from typing import Any

DEFAULT_REDACT_PATTERNS: tuple[re.Pattern[Any], ...] = (
    re.compile(r"bearer\s+[a-zA-Z0-9._-]{20,}", re.IGNORECASE),
    re.compile(r"\b(sk|pk|ghp|gho|ghu|ghs|ghr)-[a-zA-Z0-9_-]{20,}\b"),
    re.compile(r"\b[a-zA-Z0-9+/]{40,}={0,2}\b"),
    re.compile(
        r"(?i)\b(api[_\-]?key|token|secret|password)\b\s*[:=]\s*\S+",
    ),
)

_MAX_OUTPUT_LEN = 500


def redact_text(
    text: str | None,
    extra_patterns: list[re.Pattern[Any]] | None = None,
) -> str:
    """Replace secret-shaped substrings with ``[REDACTED]``.

    Pure function — no I/O side effects. Returns ``""`` for ``None`` input.
    """
    if not text:
        return "" if text is None else text

    patterns = (*DEFAULT_REDACT_PATTERNS, *(extra_patterns or ()))
    for pattern in patterns:
        text = pattern.sub("[REDACTED]", text)
    return text


def redact_env_like(data: dict[str, Any]) -> dict[str, Any]:
    """Redact dict values whose key contains secret-like tokens.

    Keys matching ``KEY``, ``TOKEN``, ``SECRET``, ``PASSWORD``, or ``AUTH``
    have their value replaced with ``[REDACTED]``.  Non-sensitive keys pass
    through unchanged.
    """
    sensitive = re.compile(r"(?i)key|token|secret|password|auth")
    return {
        k: ("[REDACTED]" if sensitive.search(k) else v) for k, v in data.items()
    }


def truncate_output(text: str, max_len: int = _MAX_OUTPUT_LEN) -> str:
    """Truncate long output to a safe prefix with a length marker."""
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}\n... [truncated, {len(text)} chars total]"
