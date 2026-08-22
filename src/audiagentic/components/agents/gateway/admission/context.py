"""Component-context callable owned by the gateway admission boundary."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias

ComponentContextReader: TypeAlias = Callable[[Path], dict[str, dict[str, Any]]]


def empty_component_context(_project_root: Path) -> dict[str, dict[str, Any]]:
    """Compatibility reader for unmanaged in-process callers and unit tests."""
    return {}


__all__ = ["ComponentContextReader", "empty_component_context"]
