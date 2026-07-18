from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from audiagentic.foundation.contracts.errors import AudiaGenticError

CliLifecycleMode = Literal["plan", "apply", "prune", "status"]


@dataclass(frozen=True)
class CliLifecycleRequest:
    """Desired-state payload for the cli-lifecycle automation family.

    Empty — project_root and provider_id are invocation context, not serialized
    payload. No caller-specific desired fields exist at this time.
    """

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CliLifecycleRequest:
        return cls()

    def to_mapping(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class CliLifecycleResult:
    """Semantic-only result for the cli-lifecycle automation family.

    No mechanic-named fields (command, returncode, stdout, stderr,
    workflow-events, probe). Redaction per Architecture Standards §4.
    """

    ok: bool
    supported: bool
    changed: bool = False
    state: str = "skipped"
    action_needed: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.state not in {"installed", "uninstalled", "skipped", "failed"}:
            raise AudiaGenticError(
                code="VAL-PCLI-001",
                kind="providers",
                message="invalid CLI lifecycle state",
                details={"state": self.state},
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CliLifecycleResult:
        return cls(
            ok=bool(value.get("ok", False)),
            supported=bool(value.get("supported", False)),
            changed=bool(value.get("changed", False)),
            state=str(value.get("state", "skipped")),
            action_needed=value.get("action_needed"),
            error_code=value.get("error_code"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "changed": self.changed,
            "state": self.state,
            "action_needed": self.action_needed,
            "error_code": self.error_code,
        }


__all__ = [
    "CliLifecycleMode",
    "CliLifecycleRequest",
    "CliLifecycleResult",
]
