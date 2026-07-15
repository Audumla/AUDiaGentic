"""Generic provider plugin-entry config capability."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginConfigSpec:
    config_path: str | Callable[[Path | None], Path]
    reader: Callable[[Path, str], dict[str, Any] | None]
    writer: Callable[[Path, str, dict[str, Any]], None]
    remover: Callable[[Path, str], bool]
    format: str = ""


__all__ = ["PluginConfigSpec"]
