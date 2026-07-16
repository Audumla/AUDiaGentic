"""Typed public contract for self-provided LSP support automation family."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SelfProvidedLspMode = Literal["apply", "status"]


@dataclass(frozen=True)
class SelfProvidedLspRequest:
    """Minimal payload for self-provided LSP provisioning."""
    project_root: str

    def to_mapping(self) -> dict[str, object]:
        return {"project_root": self.project_root}

    @classmethod
    def from_mapping(cls, value: dict) -> SelfProvidedLspRequest:
        return cls(project_root=str(value["project_root"]))


@dataclass(frozen=True)
class SelfProvidedLspResult:
    ok: bool
    supported: bool
    provider_id: str = ""
    state: str = "unknown"
    error_code: str | None = None
    action_needed: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "provider_id": self.provider_id,
            "state": self.state,
            "error_code": self.error_code,
            "action_needed": self.action_needed,
        }


__all__ = [
    "SelfProvidedLspMode",
    "SelfProvidedLspRequest",
    "SelfProvidedLspResult",
]
