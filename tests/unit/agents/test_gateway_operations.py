from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.operations import (
    GatewayOperationsApplication,
    GatewayReconcileExecutor,
    ManagementCommand,
    ManagementOperationKind,
    ManagementOperationPump,
    ManagementOperationStore,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _command(operation_id: str = "op_001") -> ManagementCommand:
    return ManagementCommand(
        operation_id=operation_id,
        kind=ManagementOperationKind.RECONCILE,
        scope={"project-id": "project-a", "dry-run": True},
        correlation_id="corr_1",
    )


def test_operation_store_is_durable_idempotent_outbox(tmp_path: Path) -> None:
    store = ManagementOperationStore(tmp_path)
    created = store.create(_command())
    repeated = store.create(_command())

    assert created["state"] == "accepted"
    assert repeated == created
    assert (store.root / "op_001" / "timeline.ndjson").exists()

    with pytest.raises(AudiaGenticError, match="CON-AGM-001"):
        store.create(
            ManagementCommand(
                operation_id="op_001",
                kind=ManagementOperationKind.ARCHIVE,
                scope={"project-id": "project-a"},
            )
        )


def test_public_operation_projection_omits_scope_and_correlation(tmp_path: Path) -> None:
    app = GatewayOperationsApplication(ManagementOperationStore(tmp_path))

    public = app.create_operation(_command())

    assert public["operation-id"] == "op_001"
    assert "scope" not in public
    assert "correlation-id" not in public


def test_claim_is_compare_and_swap_and_finish_is_owner_fenced(tmp_path: Path) -> None:
    store = ManagementOperationStore(tmp_path)
    store.create(_command())

    claimed = store.claim("op_001", owner_epoch="owner-a")
    assert claimed is not None and claimed["state"] == "running"
    assert store.claim("op_001", owner_epoch="owner-b") is None

    with pytest.raises(AudiaGenticError, match="CON-AGM-002"):
        store.finish("op_001", owner_epoch="owner-b", result={"changed": 0})

    finished = store.finish("op_001", owner_epoch="owner-a", result={"changed": 0})
    assert finished["state"] == "completed"
    assert finished["result"] == {"changed": 0}


def test_scope_and_result_are_redacted_safe(tmp_path: Path) -> None:
    store = ManagementOperationStore(tmp_path)
    with pytest.raises(AudiaGenticError, match="VAL-AGM-005"):
        store.create(
            ManagementCommand(
                operation_id="op_unsafe",
                kind=ManagementOperationKind.RECONCILE,
                scope={"prompt-body": "do not persist"},
            )
        )

    store.create(_command())
    store.claim("op_001", owner_epoch="owner-a")
    with pytest.raises(AudiaGenticError, match="VAL-AGM-006"):
        store.finish("op_001", owner_epoch="owner-a", error={"code": "X", "message": "unsafe"})


class _Executor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, operation: dict) -> dict:
        self.calls.append(operation["operation-id"])
        return {"unchanged": 1}


def test_pump_recovers_from_lost_notification_by_scanning_store(tmp_path: Path) -> None:
    store = ManagementOperationStore(tmp_path)
    app = GatewayOperationsApplication(store)
    app.create_operation(_command())
    executor = _Executor()

    completed = ManagementOperationPump(store, executor).run_once(owner_epoch="owner-a")

    assert executor.calls == ["op_001"]
    assert completed[0]["state"] == "completed"
    assert ManagementOperationPump(store, executor).run_once(owner_epoch="owner-b") == []


def test_pump_requeues_claim_from_superseded_owner_epoch(tmp_path: Path) -> None:
    store = ManagementOperationStore(tmp_path)
    store.create(_command())
    assert store.claim("op_001", owner_epoch="owner-before-restart") is not None
    executor = _Executor()

    completed = ManagementOperationPump(store, executor).run_once(owner_epoch="owner-after-restart")

    assert executor.calls == ["op_001"]
    assert completed[0]["state"] == "completed"


class _Requests:
    def __init__(self) -> None:
        self.roots: list[Path] = []

    def list_execution_requests(self, project_root: Path, **_kwargs: object) -> list[dict]:
        self.roots.append(project_root)
        return [{"state": "completed"}, {"state": "running"}, {"state": "queued"}]


def test_reconcile_is_read_only_without_positive_death_evidence(tmp_path: Path) -> None:
    executor = GatewayReconcileExecutor(_Requests())

    result = executor.execute({"scope": {"project-root": str(tmp_path)}})

    assert result == {"changed": 0, "unchanged": 1, "blocked": 2, "unknown-evidence": 2}
