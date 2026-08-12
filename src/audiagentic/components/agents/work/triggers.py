"""Pure trigger evaluation for the canonical event-to-Work ingress."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def event_pattern_matches(pattern: str, event_type: str) -> bool:
    """Match dotted event names with ``*`` (one segment) and ``**`` (rest)."""
    expected = tuple(part for part in pattern.split(".") if part)
    actual = tuple(part for part in event_type.split(".") if part)

    def match(index: int, offset: int) -> bool:
        if index == len(expected):
            return offset == len(actual)
        token = expected[index]
        if token == "**":
            return any(match(index + 1, candidate) for candidate in range(offset, len(actual) + 1))
        return offset < len(actual) and (token == "*" or token == actual[offset]) and match(index + 1, offset + 1)

    return bool(expected) and match(0, 0)


def trigger_matches(
    trigger: Mapping[str, Any],
    *,
    event_type: str,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether an enabled canonical trigger accepts an event."""
    if trigger.get("enabled", True) is not True:
        return False
    pattern = trigger.get("event-pattern", trigger.get("event_pattern"))
    if not isinstance(pattern, str) or not event_pattern_matches(pattern, event_type):
        return False
    context = {"payload": dict(payload), "metadata": dict(metadata or {})}
    for path, expected in (trigger.get("filter") or {}).items():
        value: Any = context
        for part in str(path).split("."):
            if not isinstance(value, Mapping) or part not in value:
                return False
            value = value[part]
        if value is None or (value not in expected if isinstance(expected, list) else value != expected):
            return False
    return True
