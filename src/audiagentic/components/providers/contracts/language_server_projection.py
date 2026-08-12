"""Typed provider language-server-projection capability contract."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .automation_vocabulary import ProviderReconcileMode as LanguageServerProjectionMode


@dataclass(frozen=True)
class LanguageServerEntry:
    """A single language server entry for provider config projection."""

    language: str
    command: list[str]
    file_extensions: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "command": list(self.command),
            "file_extensions": list(self.file_extensions),
            "settings": dict(self.settings),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LanguageServerEntry:
        return cls(
            language=str(value["language"]),
            command=list(value.get("command", [])),
            file_extensions=list(value.get("file_extensions", [])),
            settings=dict(value.get("settings", {})),
        )


@dataclass(frozen=True)
class LanguageServerProjectionRequest:
    """Desired language server entries for a provider."""

    entries: dict[str, LanguageServerEntry]

    def to_mapping(self) -> dict[str, object]:
        return {
            "entries": {
                lang: entry.to_mapping()
                for lang, entry in self.entries.items()
            }
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LanguageServerProjectionRequest:
        raw = value.get("entries", {})
        if not isinstance(raw, Mapping):
            raise ValueError("entries must be a mapping")
        return cls(
            entries={
                str(lang): LanguageServerEntry.from_mapping(cfg)
                for lang, cfg in raw.items()
            }
        )


@dataclass(frozen=True)
class LanguageServerProjectionResult:
    ok: bool
    supported: bool
    provider_id: str = ""
    synced: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    error_code: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "synced": list(self.synced),
            "pruned": list(self.pruned),
            "skipped": list(self.skipped),
            "error_code": self.error_code,
        }


__all__ = [
    "LanguageServerEntry",
    "LanguageServerProjectionMode",
    "LanguageServerProjectionRequest",
    "LanguageServerProjectionResult",
]
