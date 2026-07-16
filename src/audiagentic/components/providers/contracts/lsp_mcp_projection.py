"""Typed public contract for the LSP-MCP projection automation family."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

LspMcpProjectionMode = Literal["apply", "prune", "status"]


@dataclass(frozen=True)
class LspMcpProjectionEntry:
    """A single LSP-MCP server entry for provider config projection."""

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

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {"managed_id": self.managed_id, "name": self.name}
        if self.command:
            result.update(command=self.command, args=list(self.args), env=dict(self.env))
        else:
            result.update(url=self.url, headers=dict(self.headers), transport=self.transport)
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LspMcpProjectionEntry:
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


@dataclass(frozen=True)
class LspMcpProjectionRequest:
    """Desired LSP-MCP entries for provider config projection."""

    managed_ids: tuple[str, ...]
    entries: tuple[LspMcpProjectionEntry, ...] = ()

    def __post_init__(self) -> None:
        ids = [entry.managed_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("LSP-MCP managed_ids must be unique")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "managed_ids": list(self.managed_ids),
            "entries": [entry.to_mapping() for entry in self.entries],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LspMcpProjectionRequest:
        raw_entries = value.get("entries", ())
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
            raise ValueError("entries must be a collection")
        return cls(
            managed_ids=tuple(str(mid) for mid in value.get("managed_ids", ())),
            entries=tuple(LspMcpProjectionEntry.from_mapping(item) for item in raw_entries),
        )


@dataclass(frozen=True)
class LspMcpProjectionResult:
    ok: bool
    provider_id: str = ""
    synced: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    error_code: str | None = None
    action_needed: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider_id": self.provider_id,
            "synced": list(self.synced),
            "pruned": list(self.pruned),
            "skipped": list(self.skipped),
            "error_code": self.error_code,
            "action_needed": self.action_needed,
        }


@dataclass(frozen=True)
class LspMcpProjectionBatchResult:
    """Result of projecting LSP-MCP entries to all eligible providers."""
    ok: bool
    synced: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    per_provider: tuple[tuple[str, LspMcpProjectionResult], ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "synced": list(self.synced),
            "pruned": list(self.pruned),
            "skipped": list(self.skipped),
            "per_provider": [{"provider_id": pid, **r.to_mapping()} for pid, r in self.per_provider],
        }


__all__ = [
    "LspMcpProjectionEntry",
    "LspMcpProjectionMode",
    "LspMcpProjectionRequest",
    "LspMcpProjectionResult",
    "LspMcpProjectionBatchResult",
]
