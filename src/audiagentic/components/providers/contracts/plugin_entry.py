"""Typed generic provider plugin-entry capability contract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

PluginEntryMode = Literal["apply", "prune", "status"]


@dataclass(frozen=True)
class PluginEntryRequest:
    entry_id: str
    options: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("entry_id is required")

    def options_mapping(self) -> dict[str, Any]:
        return dict(self.options)


@dataclass(frozen=True)
class PluginEntryResult:
    ok: bool
    supported: bool
    changed: bool = False
    present: bool = False
    action_needed: str | None = None
    error_code: str | None = None


__all__ = ["PluginEntryMode", "PluginEntryRequest", "PluginEntryResult"]
