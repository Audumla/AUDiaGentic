"""Application authority for durable gateway operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .contracts import (
    ManagementCommand,
    ManagementOperationKind,
    ManagementWorkNotifier,
    validate_node_revoke_scope,
)
from .notifier import NoopManagementWorkNotifier, notify_best_effort
from .operation_store import ManagementOperationStore
from .retention_policy import load_retention_policy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from audiagentic.components.agents.gateway.service.shared_config import (
        SharedGatewayServerConfig,
    )


class GatewayOperationsApplication:
    """Creates/query operations; execution remains owned by a pump/executor."""

    def __init__(
        self, store: ManagementOperationStore, notifier: ManagementWorkNotifier | None = None
    ) -> None:
        self._store = store
        self._notifier = notifier or NoopManagementWorkNotifier()

    @classmethod
    def for_local_server(cls, config: SharedGatewayServerConfig) -> GatewayOperationsApplication:
        """Compose local operator storage only; never start or contact a service."""
        from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
        from audiagentic.foundation.system.managed_service import ManagedServiceStore

        service = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root)
        return cls(ManagementOperationStore(service.root))

    def create_local_node_revoke(
        self,
        *,
        operation_id: str,
        node_id: str,
        expected_grant_revision: int,
    ) -> dict[str, Any]:
        """Queue fixed local revoke intent; only the existing pump executes it.

        The generic remote creation path remains unable to select local-only
        admission. Local creation retains polling, with no startup or notifier.
        """
        scope = validate_node_revoke_scope(
            {
                "node-id": node_id,
                "expected-grant-revision": expected_grant_revision,
            }
        )
        command = ManagementCommand(operation_id, ManagementOperationKind.NODE_REVOKE, scope)
        return _project_public(self._store.create(command, local_only=True))

    def create_operation(self, command: ManagementCommand) -> dict[str, Any]:
        if command.kind in (ManagementOperationKind.PURGE, ManagementOperationKind.SESSION_PURGE):
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

    def list_operations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [_project_public(item) for item in self._store.list_records(limit=limit)]

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
