from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LanguageServerEntry:
    """A single language server entry for config projection."""

    language: str
    command: list[str]
    file_extensions: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
