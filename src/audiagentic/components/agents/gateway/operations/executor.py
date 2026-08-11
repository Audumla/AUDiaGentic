"""Gateway-operation executor composed by the standalone service host."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.application import GatewayApplication
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .archive import GatewayArchiveExecutor, GatewayPurgeExecutor
from .contracts import ManagementOperationKind
from .reconcile import GatewayReconcileExecutor


class GatewayOperationExecutor:
    """Dispatch a claimed durable operation through its closed vocabulary.

    This is intentionally a composition boundary rather than a second queue:
    the operation store supplies ordering, ownership and retry visibility;
    each effect remains in its domain-specific executor.
    """

    def __init__(self, application: GatewayApplication) -> None:
        self._reconcile = GatewayReconcileExecutor(application, terminalizer=_RequestTerminalizer())
        self._archive = GatewayArchiveExecutor(application)
        self._purge = GatewayPurgeExecutor(application)

    def execute(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            kind = ManagementOperationKind(str(operation.get("kind")))
        except ValueError as exc:
            raise AudiaGenticError(
                "VAL-AGM-009", "agents", "gateway operation kind is invalid", {}
            ) from exc
        if kind is ManagementOperationKind.RECONCILE:
            return self._reconcile.execute(operation)
        if kind is ManagementOperationKind.ARCHIVE:
            return self._archive.execute(operation)
        if kind is ManagementOperationKind.PURGE:
            return self._purge.execute(operation)
        raise AudiaGenticError("UNS-AGM-001", "agents", "gateway operation has no enabled executor", {"kind": kind})


class _RequestTerminalizer:
    """Adapter to the existing fenced recovery transition authority."""

    def terminalize_proven_dead(self, project_root, record, reason):
        owner_epoch = record.get("dispatch-owner-epoch")
        if not isinstance(owner_epoch, str) or not owner_epoch:
            raise AudiaGenticError("CON-AGM-010", "agents", "proven-dead request has no owner fence", {})
        return store.transition_recovered_terminal(
            project_root,
            str(record["request-id"]),
            "failed",
            error={
                "code": "INT-AGW-077",
                "message": "request owner was proven dead during gateway reconciliation",
                "kind": "agents",
                "details": {"evidence-reason": reason},
            },
            stale_epoch=owner_epoch,
            replay_required=False,
            replay_reason="proven-dead-reconciliation",
        )


__all__ = ["GatewayOperationExecutor"]
