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
    NODE_REVOKE = "node-revoke"


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


class NodeRevocationAuthority(Protocol):
    """Injected local authority; owns grant CAS, revocation and replay policy."""

    def revoke(self, node_id: str, *, expected_grant_revision: int) -> Any: ...


def validate_node_revoke_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    """Closed local intent: a node identifier plus its expected grant revision."""
    import re

    from audiagentic.foundation.contracts.errors import AudiaGenticError

    if (
        not isinstance(scope, Mapping)
        or set(scope) != {"node-id", "expected-grant-revision"}
        or not isinstance(scope.get("node-id"), str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", scope["node-id"]) is None
        or type(scope.get("expected-grant-revision")) is not int
        or not 1 <= scope["expected-grant-revision"] <= 2**63 - 1
    ):
        raise AudiaGenticError(
            "VAL-AGM-004", "agents",
            "node-revoke scope requires only node-id and a positive expected-grant-revision", {},
        )
    return dict(scope)


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
    "NodeRevocationAuthority",
    "validate_node_revoke_scope",
    "TargetDisposition",
    "WorkEvidence",
]
