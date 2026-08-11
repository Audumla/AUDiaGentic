"""Closed contracts for gateway operations (SH24 Slice A)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class ManagementOperationKind(StrEnum):
    """The closed v1 gateway operation vocabulary."""

    RECONCILE = "reconcile"
    ARCHIVE = "archive"
    PURGE = "purge"


class WorkEvidence(StrEnum):
    """Evidence classification; never a gateway-operation workflow state."""

    LIVE = "live"
    PROVEN_DEAD = "proven-dead"
    UNKNOWN = "unknown"


class TargetDisposition(StrEnum):
    """Per-target result; never a gateway-operation workflow state."""

    CHANGED = "changed"
    UNCHANGED = "unchanged"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ManagementCommand:
    """Idempotent, redacted-safe request to perform gateway operator work.

    ``scope`` deliberately carries identifiers and selectors only.  Raw agent
    prompts, output, credentials, and provider-native handles are forbidden
    at the store boundary.
    """

    operation_id: str
    kind: ManagementOperationKind
    scope: Mapping[str, Any]
    correlation_id: str | None = None


class ManagementWorkNotifier(Protocol):
    """Best-effort wake-up transport, not an authoritative work queue."""

    def notify(self, operation_id: str) -> None:
        """Request a pump wake-up for an already durable operation id."""


class ManagementOperationExecutor(Protocol):
    """Provider-independent effect boundary used by the local pump."""

    def execute(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        """Perform one claimed operation and return a redacted result summary."""
        ...


__all__ = [
    "ManagementCommand",
    "ManagementOperationExecutor",
    "ManagementOperationKind",
    "ManagementWorkNotifier",
    "TargetDisposition",
    "WorkEvidence",
]
