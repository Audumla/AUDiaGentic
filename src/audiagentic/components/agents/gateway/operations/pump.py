"""Local durable pump for advisory-notified gateway operations."""

from __future__ import annotations

from typing import Any

from .contracts import ManagementOperationExecutor
from .operation_store import ManagementOperationStore


class ManagementOperationPump:
    """Claims durable operations; duplicate/lost notifications are harmless."""

    def __init__(self, store: ManagementOperationStore, executor: ManagementOperationExecutor) -> None:
        self._store = store
        self._executor = executor

    def run_once(self, *, owner_epoch: str, limit: int = 100) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        self._store.recover_prior_owner_claims(owner_epoch=owner_epoch)
        for candidate in self._store.list_dispatchable(limit=limit):
            operation = self._store.claim(candidate["operation-id"], owner_epoch=owner_epoch)
            if operation is None:
                continue
            try:
                result = self._executor.execute(operation)
                completed.append(
                    self._store.finish(operation["operation-id"], owner_epoch=owner_epoch, result=result)
                )
            except Exception:  # noqa: BLE001 - durable public result stays redacted
                completed.append(
                    self._store.fail(
                        operation["operation-id"], owner_epoch=owner_epoch, code="INT-AGM-001"
                    )
                )
        return completed


__all__ = ["ManagementOperationPump"]
