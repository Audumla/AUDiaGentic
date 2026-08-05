"""Typed generic provider plugin-entry capability contract."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeAlias

PluginEntryMode = Literal["apply", "prune", "status"]
PluginOptionValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class PluginEntryRequest:
    entry_id: str
    ownership_scope: str
    options: tuple[tuple[str, PluginOptionValue], ...] = ()

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("entry_id is required")
        if not self.ownership_scope:
            raise ValueError("ownership_scope is required")
        if len({key for key, _ in self.options}) != len(self.options):
            raise ValueError("plugin option names must be unique")
        if any(
            not key or not isinstance(value, (str, int, float, bool, type(None)))
            for key, value in self.options
        ):
            raise ValueError("plugin options require non-empty names and JSON scalar values")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PluginEntryRequest:
        raw_options = value.get("options", {})
        if not isinstance(raw_options, Mapping):
            raise ValueError("plugin options must be a mapping")
        return cls(
            entry_id=str(value["entry_id"]),
            ownership_scope=str(value["ownership_scope"]),
            options=tuple(sorted((str(key), item) for key, item in raw_options.items())),
        )

    def options_mapping(self) -> dict[str, PluginOptionValue]:
        return dict(self.options)

    def to_mapping(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "ownership_scope": self.ownership_scope,
            "options": self.options_mapping(),
        }


@dataclass(frozen=True)
class PluginEntryResult:
    ok: bool
    supported: bool
    provider_id: str = ""
    changed: bool = False
    present: bool = False
    action_needed: str | None = None
    error_code: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "provider_id": self.provider_id,
            "changed": self.changed,
            "present": self.present,
            "action_needed": self.action_needed,
            "error_code": self.error_code,
        }


__all__ = ["PluginEntryMode", "PluginOptionValue", "PluginEntryRequest", "PluginEntryResult"]
