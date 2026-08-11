"""Gateway-operation executor composed by the standalone service host."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from audiagentic.components.agents.gateway.application import GatewayApplication
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .contracts import ManagementOperationKind
from .reconcile import GatewayReconcileExecutor


class GatewayOperationExecutor:
    """Dispatch a claimed durable operation through its closed vocabulary.

    This is intentionally a composition boundary rather than a second queue:
    the operation store supplies ordering, ownership and retry visibility;
    each effect remains in its domain-specific executor.
    """

    def __init__(self, application: GatewayApplication) -> None:
        self._reconcile = GatewayReconcileExecutor(application)

    def execute(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            kind = ManagementOperationKind(str(operation.get("kind")))
        except ValueError as exc:
            raise AudiaGenticError(
                "VAL-AGM-009", "agents", "gateway operation kind is invalid", {}
            ) from exc
        if kind is ManagementOperationKind.RECONCILE:
            return self._reconcile.execute(operation)
        # Archive/purge cannot silently become an unsafe generic file action.
        # Their policy/retention executors are wired only when their explicit
        # safety gates are present.
        raise AudiaGenticError(
            "UNS-AGM-001", "agents", "gateway operation has no enabled executor", {"kind": kind}
        )


__all__ = ["GatewayOperationExecutor"]
