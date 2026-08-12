"""Typed public contract for self-provided LSP support automation family."""
from __future__ import annotations

from dataclasses import dataclass

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .automation_vocabulary import ProviderApplyStatusMode as SelfProvidedLspMode

_VALID_STATES = {"provisioned", "needs-action", "unknown"}


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

    def __post_init__(self) -> None:
        if self.state not in _VALID_STATES:
            raise AudiaGenticError(
                code="VAL-PLSP-001",
                kind="providers",
                message="invalid self-provided-LSP state",
                details={"state": self.state},
            )

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
