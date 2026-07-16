"""Shared output redaction primitives.

Generalized from ``_RedactionFilter`` in ``foundation/logging/audit.py``.
Domain-neutral — safe to import from any layer without pulling in recipe or
component machinery.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

DEFAULT_REDACT_PATTERNS: tuple[re.Pattern[Any], ...] = (
    re.compile(r"bearer\s+[a-zA-Z0-9._-]{20,}", re.IGNORECASE),
    re.compile(r"\b(sk|pk|ghp|gho|ghu|ghs|ghr)-[a-zA-Z0-9_-]{20,}\b"),
    re.compile(r"\b[a-zA-Z0-9+/]{40,}={0,2}\b"),
    re.compile(
        r"(?i)(\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*)\S+",
    ),
    re.compile(
        r"(https?://)([^@/]+:[^@/]+@)",  # URL-embedded credentials
        re.IGNORECASE,
    ),
)

_MAX_OUTPUT_LEN = 500


def redact_text(
    text: str | None,
    extra_patterns: list[re.Pattern[Any]] | None = None,
) -> str:
    """Replace secret-shaped substrings with ``[REDACTED]``.

    Pure function — no I/O side effects. Returns ``""`` for ``None`` input.
    URL-embedded credentials (e.g. ``https://user:pass@host``) are redacted
    to ``https://[REDACTED]@host``, preserving the base URL.
    """
    if not text:
        return "" if text is None else text

    patterns = (*DEFAULT_REDACT_PATTERNS, *(extra_patterns or ()))
    for pattern in patterns:
        # The URL-credential pattern has two capture groups; replace only the
        # credentials group while preserving scheme and host.
        if pattern.pattern.startswith(r"(https?://"):
            text = pattern.sub(r"\1[REDACTED]@", text)
        # The key-value pattern preserves the key (e.g. "token: [REDACTED]").
        elif r"\b(?:api[_-]?key|token|secret|password)" in pattern.pattern:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
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


# ---------------------------------------------------------------------------
# Structural summarization (EDJ24) — the sole sensitive-key matcher lives here.
# ---------------------------------------------------------------------------

SECRET_KEYS: re.Pattern[str] = re.compile(
    r"(?i)key|token|secret|password|authorization|auth"
)

BULK_KEYS: re.Pattern[str] = re.compile(
    r"(?i)stdout|stderr|output|input|prompt"
)

# Backwards compat alias — consumers of the old name get SECRET_KEYS only.
SENSITIVE_KEY_PATTERN: re.Pattern[str] = SECRET_KEYS

_REDACTED = "[REDACTED]"
_TRUNCATED = "[TRUNCATED]"
_MAX_STRUCT_DEPTH = 8
_MAX_STRUCT_ENTRIES = 20
_MAX_LEAF_STR_LEN = 80

# Metadata keys safe to persist verbatim (values are still recursively redacted).
_SAFE_METADATA_KEYS: tuple[str, ...] = (
    "correlation_id",
    "correlation-id",
    "subject",
    "job-id",
    "trigger-id",
    "source-component",
)


def is_sensitive_key(key: Any) -> bool:
    """Return True when a mapping key looks secret-bearing (SECRET_KEYS only)."""
    return bool(SECRET_KEYS.search(str(key)))


def is_bulk_key(key: Any) -> bool:
    """Return True for diagnostic-channel keys whose values are redacted + truncated, not blanked."""
    return bool(BULK_KEYS.search(str(key)))


def _summarize_value(value: Any, depth: int) -> Any:
    if depth > _MAX_STRUCT_DEPTH:
        return _TRUNCATED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)[:_MAX_LEAF_STR_LEN]
    if isinstance(value, (bytes, bytearray)):
        return f"[{len(value)} bytes]"
    if isinstance(value, Mapping):
        items = list(value.items())
        summarized: dict[str, Any] = {}
        for k, v in items[:_MAX_STRUCT_ENTRIES]:
            key_str = str(k)
            if is_sensitive_key(key_str):
                summarized[key_str] = _REDACTED
            elif is_bulk_key(key_str):
                summarized[key_str] = redact_text(v)[:_MAX_LEAF_STR_LEN]
            else:
                summarized[key_str] = _summarize_value(v, depth + 1)
        if len(items) > _MAX_STRUCT_ENTRIES:
            summarized[_TRUNCATED] = f"{len(items) - _MAX_STRUCT_ENTRIES} entries omitted"
        return summarized
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        summarized_list = [_summarize_value(v, depth + 1) for v in items[:_MAX_STRUCT_ENTRIES]]
        if len(items) > _MAX_STRUCT_ENTRIES:
            summarized_list.append(_TRUNCATED)
        return summarized_list
    return redact_text(str(value))[:_MAX_LEAF_STR_LEN]


def summarize_structure(value: Any, *, max_len: int = 500) -> str:
    """Return a deterministic, redacted, bounded JSON summary of *value*.

    Never raises. Sensitive keys (see :data:`SENSITIVE_KEY_PATTERN`) have their
    values replaced with ``[REDACTED]``; other strings pass through
    :func:`redact_text` and are truncated. Traversal is bounded in depth and
    entry count; the result never exceeds *max_len* characters.
    """
    try:
        text = json.dumps(_summarize_value(value, 0), sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 — summarizer must never raise
        return _REDACTED
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - len(_TRUNCATED))] + _TRUNCATED


def _redact_error_value(key: str, value: Any) -> Any:
    """Recursively redact an error detail value by key sensitivity."""
    if is_sensitive_key(key):
        return _REDACTED
    if is_bulk_key(key):
        return redact_text(value)[:_MAX_LEAF_STR_LEN] if isinstance(value, str) else value
    if isinstance(value, str):
        return redact_text(value)[:_MAX_LEAF_STR_LEN]
    if isinstance(value, dict):
        return {str(k): _redact_error_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_error_value(key, item) for item in value]
    return value


def redact_error_envelope(error: Any) -> dict[str, Any]:
    """Redact an error envelope's details dict using shared primitives.

    Accepts an AudiaGenticError or a dict already shaped as an error envelope.
    Sensitive keys are replaced with ``[REDACTED]``; other string values pass
    through :func:`redact_text` and are truncated.
    """
    from audiagentic.foundation.contracts.errors import to_error_envelope

    if hasattr(error, 'code'):  # AudiaGenticError instance
        envelope = to_error_envelope(error)
    elif isinstance(error, dict):
        envelope = error
    else:
        return {"error": str(error)}

    details = envelope.get("details")
    if isinstance(details, dict):
        envelope["details"] = {
            str(key): _redact_error_value(str(key), value)
            for key, value in details.items()
        }
    return envelope


def safe_metadata(metadata: Any) -> dict[str, Any]:
    """Return only allowlisted metadata keys with recursively redacted values.

    Never raises; non-mapping input yields ``{}``. The allowlist is fixed here —
    consumers must not define local variants.
    """
    if not isinstance(metadata, Mapping):
        return {}
    try:
        return {
            key: _summarize_value(metadata[key], 0)
            for key in _SAFE_METADATA_KEYS
            if key in metadata
        }
    except Exception:  # noqa: BLE001 — must never raise
        return {}
