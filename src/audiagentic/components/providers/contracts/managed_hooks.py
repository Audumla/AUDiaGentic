"""Typed public contract for the managed-hooks automation family."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

ManagedHooksMode = Literal["apply", "prune", "status"]


@dataclass(frozen=True)
class ManagedHooksEntry:
    managed_id: str
    event: str
    command: str
    timeout: int | None = None

    def __post_init__(self) -> None:
        if not self.managed_id or not self.event or not self.command:
            raise ValueError("managed_id, event, and command are required")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ManagedHooksEntry:
        return cls(
            managed_id=str(value["managed_id"]),
            event=str(value["event"]),
            command=str(value["command"]),
            timeout=int(value["timeout"]) if value.get("timeout") else None,
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "managed_id": self.managed_id,
            "event": self.event,
            "command": self.command,
        }
        if self.timeout is not None:
            result["timeout"] = self.timeout
        return result


@dataclass(frozen=True)
class ManagedHooksRequest:
    ownership_scope: str
    entries: tuple[ManagedHooksEntry, ...] = ()

    def __post_init__(self) -> None:
        if not self.ownership_scope:
            raise ValueError("ownership_scope is required")
        ids = [entry.managed_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("managed hook ids must be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ManagedHooksRequest:
        raw_entries = value.get("entries", ())
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
            raise ValueError("entries must be a collection")
        return cls(
            ownership_scope=str(value["ownership_scope"]),
            entries=tuple(ManagedHooksEntry.from_mapping(item) for item in raw_entries),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ownership_scope": self.ownership_scope,
            "entries": [entry.to_mapping() for entry in self.entries],
        }


@dataclass(frozen=True)
class ManagedHooksResult:
    ok: bool
    supported: bool = True
    changed: bool = False
    provider_id: str = ""
    managed_ids: tuple[str, ...] = ()
    removed_ids: tuple[str, ...] = ()
    collision_ids: tuple[str, ...] = ()
    action_needed: str | None = None
    error_code: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "changed": self.changed,
            "provider_id": self.provider_id,
            "managed_ids": list(self.managed_ids),
            "removed_ids": list(self.removed_ids),
            "collision_ids": list(self.collision_ids),
            "action_needed": self.action_needed,
            "error_code": self.error_code,
        }


__all__ = [
    "ManagedHooksEntry",
    "ManagedHooksMode",
    "ManagedHooksRequest",
    "ManagedHooksResult",
]
