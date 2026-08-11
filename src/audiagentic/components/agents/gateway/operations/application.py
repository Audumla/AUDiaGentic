"""Application authority for durable gateway operations."""

from __future__ import annotations

import logging
from typing import Any

from .contracts import ManagementCommand, ManagementOperationKind, ManagementWorkNotifier
from .notifier import NoopManagementWorkNotifier, notify_best_effort
from .operation_store import ManagementOperationStore
from .retention_policy import load_retention_policy

logger = logging.getLogger(__name__)


class GatewayOperationsApplication:
    """Creates/query operations; execution remains owned by a pump/executor."""

    def __init__(
        self, store: ManagementOperationStore, notifier: ManagementWorkNotifier | None = None
    ) -> None:
        self._store = store
        self._notifier = notifier or NoopManagementWorkNotifier()

    def create_operation(self, command: ManagementCommand) -> dict[str, Any]:
        if command.kind is ManagementOperationKind.PURGE:
            # Snapshot machine policy into immutable operation intent.  A
            # project cannot supply or weaken this authority.
            policy = load_retention_policy()
            scope = dict(command.scope)
            scope["retention-policy"] = policy.snapshot
            command = ManagementCommand(
                operation_id=command.operation_id,
                kind=command.kind,
                scope=scope,
                correlation_id=command.correlation_id,
            )
        operation = self._store.create(command)
        if operation["state"] == "accepted" and not notify_best_effort(
            self._notifier, operation["operation-id"]
        ):
            logger.warning(
                "gateway operation notification deferred",
                extra={"operation_id": operation["operation-id"]},
            )
        return _project_public(operation)

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        return _project_public(self._store.read(operation_id))

    def has_active_operations(self) -> bool:
        """Expose the one lifecycle fact needed by the service admission gate."""
        return self._store.active_count() > 0


def _project_public(operation: dict[str, Any]) -> dict[str, Any]:
    """Expose only bounded operator status, never selector/path internals."""
    visible = (
        "contract-version",
        "operation-id",
        "kind",
        "state",
        "revision",
        "created-at",
        "updated-at",
        "started-at",
        "finished-at",
        "result",
        "error",
    )
    return {field: operation.get(field) for field in visible}


__all__ = ["GatewayOperationsApplication"]
