"""Event type pattern matching with wildcard support."""
from __future__ import annotations


def pattern_matches(pattern: str, event_type: str) -> bool:
    """Check if event type matches pattern with wildcard support.

    Supports:
    - * matches exactly one segment
    - ** matches zero or more segments
    """
    parts = pattern.split(".")
    event_parts = event_type.split(".")

    if "**" in parts:
        wildcard_idx = parts.index("**")
        prefix = parts[:wildcard_idx]
        suffix = parts[wildcard_idx + 1:]

        if len(event_parts) < len(prefix) + len(suffix):
            return False

        if event_parts[:len(prefix)] != prefix:
            return False

        if suffix and event_parts[-len(suffix):] != suffix:
            return False

        return True
    else:
        if len(parts) != len(event_parts):
            return False

        for p, e in zip(parts, event_parts):
            if p != "*" and p != e:
                return False

        return True
