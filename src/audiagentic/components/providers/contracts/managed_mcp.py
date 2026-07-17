"""Typed public contract for the managed-MCP automation family."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

ManagedMcpMode = Literal["apply", "prune", "status"]


@dataclass(frozen=True)
class ManagedMcpEntry:
    managed_id: str
    name: str
    command: str | None = None
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    url: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    transport: Literal["http", "sse"] | None = None

    def __post_init__(self) -> None:
        if not self.managed_id or not self.name:
            raise ValueError("managed_id and name are required")
        if bool(self.command) == bool(self.url):
            raise ValueError("entry requires exactly one of command or url")
        if self.url is None and self.transport is not None:
            raise ValueError("transport requires url")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ManagedMcpEntry:
        return cls(
            managed_id=str(value["managed_id"]),
            name=str(value["name"]),
            command=str(value["command"]) if value.get("command") else None,
            args=tuple(str(item) for item in value.get("args", ())),
            env=tuple(sorted((str(k), str(v)) for k, v in dict(value.get("env", {})).items())),
            url=str(value["url"]) if value.get("url") else None,
            headers=tuple(sorted((str(k), str(v)) for k, v in dict(value.get("headers", {})).items())),
            transport=value.get("transport"),
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {"managed_id": self.managed_id, "name": self.name}
        if self.command:
            result.update(command=self.command, args=list(self.args), env=dict(self.env))
        else:
            result.update(url=self.url, headers=dict(self.headers), transport=self.transport)
        return result


@dataclass(frozen=True)
class ManagedMcpRequest:
    ownership_scope: str
    entries: tuple[ManagedMcpEntry, ...] = ()

    def __post_init__(self) -> None:
        if not self.ownership_scope:
            raise ValueError("ownership_scope is required")
        ids = [entry.managed_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("managed MCP ids must be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ManagedMcpRequest:
        raw_entries = value.get("entries", ())
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
            raise ValueError("entries must be a collection")
        return cls(
            ownership_scope=str(value["ownership_scope"]),
            entries=tuple(ManagedMcpEntry.from_mapping(item) for item in raw_entries),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ownership_scope": self.ownership_scope,
            "entries": [entry.to_mapping() for entry in self.entries],
        }


@dataclass(frozen=True)
class ManagedMcpResult:
    ok: bool
    supported: bool
    provider_id: str = ""
    changed: bool = False
    managed_ids: tuple[str, ...] = ()
    removed_ids: tuple[str, ...] = ()
    collision_ids: tuple[str, ...] = ()
    auto_refreshed: bool = True
    action_needed: str | None = None
    error_code: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "provider_id": self.provider_id,
            "changed": self.changed,
            "managed_ids": list(self.managed_ids),
            "removed_ids": list(self.removed_ids),
            "collision_ids": list(self.collision_ids),
            "auto_refreshed": self.auto_refreshed,
            "action_needed": self.action_needed,
            "error_code": self.error_code,
        }


__all__ = ["ManagedMcpEntry", "ManagedMcpMode", "ManagedMcpRequest", "ManagedMcpResult"]
