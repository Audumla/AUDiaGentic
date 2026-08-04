"""Small mapping-normalization primitives shared by agent gateway boundaries."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Return the value for the first present key, preserving explicit ``None``."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


__all__ = ["first_present"]
