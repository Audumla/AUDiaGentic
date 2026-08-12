# pyright: reportArgumentType=false, reportOptionalMemberAccess=false
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import store as request_store
from audiagentic.components.agents.gateway.application import InProcessGatewayApplication
from audiagentic.components.agents.gateway.operations import (
    GatewayOperationExecutor,
    GatewayOperationsApplication,
    GatewayReconcileExecutor,
    ManagementCommand,
    ManagementOperationKind,
    ManagementOperationPump,
    ManagementOperationStore,
)
from audiagentic.components.agents.gateway.operations.archive import (
    GatewayArchiveExecutor,
    GatewayPurgeExecutor,
)
from audiagentic.components.agents.gateway.operations.contracts import WorkEvidence
from audiagentic.components.agents.gateway.operations.evidence import (
    EvidenceFinding,
    GatewayWorkEvidenceReader,
)
from audiagentic.components.agents.gateway.operations.retention_policy import load_retention_policy
from audiagentic.components.agents.gateway.session.retention import request_retention_pin
from audiagentic.components.agents.gateway.session.sessions_store import (
    build_session_record,
    record_session_turn,
    write_session_record,
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


def test_operation_inventory_is_bounded_and_redacted(tmp_path: Path) -> None:
    app = GatewayOperationsApplication(ManagementOperationStore(tmp_path))
    app.create_operation(_command("op_001"))
    app.create_operation(_command("op_002"))

    inventory = app.list_operations(limit=1)

    assert len(inventory) == 1
    assert inventory[0]["operation-id"] == "op_002"
    assert "scope" not in inventory[0]
    assert "correlation-id" not in inventory[0]


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


def test_public_create_real_executor_restart_race_fences_request_terminal_transition(tmp_path: Path) -> None:
    """SH24 A-D proof: public operation -> pump -> real fenced request transition."""
    request = request_store.build_record(
        execution_profile_id="review", prompt_body="reconcile",
    )
    request_store.write_record(tmp_path, request)
    claimed = request_store.claim_dispatch(
        tmp_path, request["request-id"], owner_epoch="request-owner",
        expected_revision=0,
    )
    running = request_store.start_owned_attempt(
        tmp_path, request["request-id"], owner_epoch="request-owner",
        worker_id="worker-proof", expected_revision=claimed["revision"],
    )

    class Application(InProcessGatewayApplication):
        def list_execution_requests(self, project_root: Path, **_kwargs: object) -> list[dict]:
            record = request_store.read_record(project_root, running["request-id"])
            record["reconciliation-evidence"] = {
                "classification": "proven-dead",
                "worker-id": record["worker-id"],
                "attempt-epoch": record["attempt-epoch"],
            }
            return [record]

    operation_store = ManagementOperationStore(tmp_path)
    public_app = GatewayOperationsApplication(operation_store)
    created = public_app.create_operation(
        ManagementCommand(
            operation_id="op-real-proof",
            kind=ManagementOperationKind.RECONCILE,
            scope={"project-root": str(tmp_path)},
        )
    )
    assert created["state"] == "accepted"
    # Simulate a host crash after claim; the restarted pump must recover the
    # operation and use the real executor/terminalizer exactly once.
    assert operation_store.claim("op-real-proof", owner_epoch="host-before-restart")
    completed = ManagementOperationPump(
        operation_store, GatewayOperationExecutor(Application())
    ).run_once(owner_epoch="host-after-restart")

    assert completed[0]["state"] == "completed"
    terminal = request_store.read_record(tmp_path, running["request-id"])
    assert terminal["state"] == "failed"
    assert terminal["error"]["code"] == "INT-AGW-077"


class _Requests:
    def __init__(self) -> None:
        self.roots: list[Path] = []

    def list_execution_requests(self, project_root: Path, **_kwargs: object) -> list[dict]:
        self.roots.append(project_root)
        return [{"state": "completed"}, {"state": "running"}, {"state": "queued"}]


def test_reconcile_is_read_only_without_positive_death_evidence(tmp_path: Path) -> None:
    executor = GatewayReconcileExecutor(_Requests())

    result = executor.execute({"scope": {"project-root": str(tmp_path)}})

    assert result == {"changed": 0, "unchanged": 1, "blocked": 2, "unknown-evidence": 2, "live": 0}


def test_evidence_requires_matching_owner_fence_and_never_uses_silence() -> None:
    reader = GatewayWorkEvidenceReader()
    base = {"state": "running", "worker-id": "w1", "attempt-epoch": 2}

    assert reader.assess({**base, "silence-seconds": 999}).evidence.value == "unknown"
    assert reader.assess({**base, "reconciliation-evidence": {"classification": "live"}}).evidence.value == "live"
    assert reader.assess({
        **base,
        "reconciliation-evidence": {
            "classification": "proven-dead", "worker-id": "w2", "attempt-epoch": 2
        },
    }).evidence.value == "unknown"
    assert reader.assess({
        **base,
        "reconciliation-evidence": {
            "classification": "proven-dead", "worker-id": "w1", "attempt-epoch": 2
        },
    }).evidence.value == "proven-dead"


class _LiveEvidence:
    def assess(self, _record: dict) -> EvidenceFinding:
        return EvidenceFinding(WorkEvidence.LIVE, "live")


def test_reconcile_reports_live_separately_from_unknown(tmp_path: Path) -> None:
    class _LiveRequests:
        def list_execution_requests(self, _root: Path, **_kwargs: object) -> list[dict]:
            return [{"state": "running"}]

    result = GatewayReconcileExecutor(_LiveRequests(), evidence=_LiveEvidence()).execute(
        {"scope": {"project-root": str(tmp_path)}}
    )
    assert result["live"] == 1
    assert result["unknown-evidence"] == 0


def test_reconcile_terminalizes_only_fenced_proven_dead_targets(tmp_path: Path) -> None:
    class _Requests:
        def list_execution_requests(self, _root: Path, **_kwargs: object) -> list[dict]:
            return [{
                "request-id": "req_dead",
                "state": "running",
                "worker-id": "worker-1",
                "attempt-epoch": 2,
                "dispatch-owner-epoch": "owner-1",
                "reconciliation-evidence": {
                    "classification": "proven-dead",
                    "worker-id": "worker-1",
                    "attempt-epoch": 2,
                },
            }]

    class _Terminalizer:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def terminalize_proven_dead(self, _root: Path, record: dict, reason: str) -> dict:
            self.calls.append((record["request-id"], reason))
            return {**record, "state": "failed"}

    terminalizer = _Terminalizer()
    result = GatewayReconcileExecutor(
        _Requests(), terminalizer=terminalizer  # type: ignore[arg-type]
    ).execute({"scope": {"project-root": str(tmp_path)}})

    assert result == {"changed": 1, "unchanged": 0, "blocked": 0, "unknown-evidence": 0, "live": 0}
    assert terminalizer.calls == [("req_dead", "fenced-owner-death-evidence")]
    assert result["blocked"] == 0


class _ArchiveRequests:
    def __init__(self, record: dict) -> None:
        self.record = record

    def get_execution_request(self, _root: Path, _request_id: str) -> dict:
        return dict(self.record)

    def list_execution_requests(self, _root: Path, **_kwargs: object) -> list[dict]:
        return [dict(self.record)]


def test_archive_is_integrity_manifest_and_purge_fails_closed_without_policy(tmp_path: Path) -> None:
    request_id = "req_archive_1"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed"})

    archived = GatewayArchiveExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}})
    assert archived == {"changed": 1, "blocked": 0}
    manifest = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "archive" / request_id / "archive-manifest.json"
    assert manifest.is_file()
    blocked = GatewayPurgeExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": {}}})
    assert blocked["reason"] == "RETENTION_POLICY_UNAVAILABLE"
    assert request_dir.exists()


def test_archive_preserves_durable_runtime_lineage_for_resume(tmp_path: Path) -> None:
    request_id = "req_archive_resume"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    runtime_dir = request_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed","session-id":"ses_resume"}', encoding="utf-8")
    (runtime_dir / "provider-session.json").write_text('{"continuation":"opaque"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed", "session-id": "ses_resume"})

    result = GatewayArchiveExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}})

    assert result == {"changed": 1, "blocked": 0}
    archived_runtime = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "archive" / request_id / "runtime" / "provider-session.json"
    assert archived_runtime.is_file()


def test_archive_replay_is_idempotent_and_preserves_manifest(tmp_path: Path) -> None:
    request_id = "req_archive_idempotent"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed"})
    scope = {"project-root": str(tmp_path), "request-ids": [request_id]}

    first = GatewayArchiveExecutor(fake).execute({"scope": scope})
    second = GatewayArchiveExecutor(fake).execute({"scope": scope})

    assert first == {"changed": 1, "blocked": 0}
    assert second == {"changed": 0, "blocked": 0}
    assert (tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "archive" / request_id / "archive-manifest.json").is_file()


def test_purge_revalidates_policy_and_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_path = tmp_path / "machine-policy.json"
    policy_path.write_text('{"policy-id":"p1","purge-enabled":true,"minimum-archive-age-seconds":0.01,"max-batch-size":2}', encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_archive_2"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed"})
    GatewayArchiveExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}})
    time.sleep(0.02)
    snapshot = load_retention_policy().snapshot
    result = GatewayPurgeExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": snapshot}})
    assert result == {"changed": 1, "blocked": 0}
    assert not request_dir.exists()


def test_purge_replay_is_idempotent_after_archive_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_path = tmp_path / "machine-policy.json"
    policy_path.write_text(
        '{"policy-id":"p1","purge-enabled":true,"minimum-archive-age-seconds":0.01,"max-batch-size":2}',
        encoding="utf-8",
    )
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_purge_idempotent"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed"})
    GatewayArchiveExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}})
    time.sleep(0.02)
    scope = {
        "project-root": str(tmp_path),
        "request-ids": [request_id],
        "retention-policy": load_retention_policy().snapshot,
    }

    first = GatewayPurgeExecutor(fake).execute({"scope": scope})
    second = GatewayPurgeExecutor(fake).execute({"scope": scope})

    assert first == {"changed": 1, "blocked": 0}
    assert second == {"changed": 0, "blocked": 0}
    assert not request_dir.exists()


def test_purge_blocks_changed_attempt_fence_after_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_path = tmp_path / "machine-policy.json"
    policy_path.write_text('{"policy-id":"p1","purge-enabled":true,"minimum-archive-age-seconds":0.01,"max-batch-size":2}', encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_archive_3"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed", "attempt-epoch": 1})
    GatewayArchiveExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}})
    time.sleep(0.02)
    snapshot = load_retention_policy().snapshot
    fake.record["attempt-epoch"] = 2
    result = GatewayPurgeExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": snapshot}})
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()


def test_purge_final_pin_recheck_wins_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_path = tmp_path / "machine-policy.json"
    policy_path.write_text('{"policy-id":"p1","purge-enabled":true,"minimum-archive-age-seconds":0.01,"max-batch-size":2}', encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_archive_4"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed"})
    GatewayArchiveExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}})
    time.sleep(0.02)
    snapshot = load_retention_policy().snapshot
    import audiagentic.components.agents.gateway.operations.archive as archive_module
    calls = {"count": 0}
    def _pin_after_census(_root: Path, _request: str):
        calls["count"] += 1
        return type("Pin", (), {"pinned": calls["count"] > 1})()
    monkeypatch.setattr(archive_module, "request_retention_pin", _pin_after_census)
    monkeypatch.setattr(archive_module, "_request_retention_pin_unlocked", _pin_after_census)
    result = GatewayPurgeExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": snapshot}})
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()


def _enabled_retention_policy(path: Path) -> None:
    path.write_text(
        '{"policy-id":"p1","purge-enabled":true,"minimum-archive-age-seconds":0.01,"max-batch-size":2}',
        encoding="utf-8",
    )


def _archive_completed_request(tmp_path: Path, request_id: str, fake: _ArchiveRequests) -> Path:
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    assert GatewayArchiveExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}}
    ) == {"changed": 1, "blocked": 0}
    time.sleep(0.02)
    return request_dir


def test_purge_final_fence_blocks_changed_request_record_after_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_changed_fence"

    class ChangingRequests(_ArchiveRequests):
        calls = 0

        def get_execution_request(self, root: Path, request: str) -> dict:
            self.calls += 1
            if self.calls >= 3:  # purge's immediate pre-delete re-read
                return {"state": "completed", "attempts": [{"attempt": 2}]}
            return super().get_execution_request(root, request)

    fake = ChangingRequests({"state": "completed", "attempts": [{"attempt": 1}]})
    request_dir = _archive_completed_request(tmp_path, request_id, fake)
    result = GatewayPurgeExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
    )
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()


def test_purge_final_fence_blocks_machine_policy_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_policy_fence"

    class PolicyChangingRequests(_ArchiveRequests):
        calls = 0

        def get_execution_request(self, root: Path, request: str) -> dict:
            self.calls += 1
            # The first purge read happens after the policy snapshot check;
            # change policy here to exercise the immediate pre-delete fence.
            if self.calls == 2:
                policy_path.write_text(
                    '{"policy-id":"p1","purge-enabled":false,"minimum-archive-age-seconds":0.01,"max-batch-size":2}',
                    encoding="utf-8",
                )
            return super().get_execution_request(root, request)

    fake = PolicyChangingRequests({"state": "completed"})
    request_dir = _archive_completed_request(tmp_path, request_id, fake)
    result = GatewayPurgeExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
    )
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()


def test_purge_final_fence_blocks_archive_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_archive_content_fence"
    archive_path: Path | None = None

    class ArchiveChangingRequests(_ArchiveRequests):
        calls = 0

        def get_execution_request(self, root: Path, request: str) -> dict[str, object]:
            self.calls += 1
            if self.calls == 3 and archive_path is not None:
                (archive_path / "record.json").write_text('{"state":"tampered"}', encoding="utf-8")
            return super().get_execution_request(root, request)

    fake = ArchiveChangingRequests({"state": "completed"})
    request_dir = _archive_completed_request(tmp_path, request_id, fake)
    archive_path = (
        tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "archive" / request_id
    )
    result = GatewayPurgeExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
    )
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()
    assert archive_path.exists()


def test_purge_final_fence_blocks_policy_withdrawal_at_delete_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_policy_final_boundary"

    class FinalPolicyChangingRequests(_ArchiveRequests):
        calls = 0

        def get_execution_request(self, root: Path, request: str) -> dict[str, object]:
            self.calls += 1
            if self.calls == 2:
                policy_path.write_text(
                    '{"policy-id":"p1","purge-enabled":false,"minimum-archive-age-seconds":0.01,"max-batch-size":2}',
                    encoding="utf-8",
                )
            return super().get_execution_request(root, request)

    fake = FinalPolicyChangingRequests({"state": "completed"})
    request_dir = _archive_completed_request(tmp_path, request_id, fake)
    result = GatewayPurgeExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
    )
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()


def test_purge_final_fence_blocks_attempt_epoch_change_during_census(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_attempt_final_boundary"

    class FinalAttemptChangingRequests(_ArchiveRequests):
        calls = 0

        def get_execution_request(self, root: Path, request: str) -> dict[str, object]:
            self.calls += 1
            if self.calls == 2:
                self.record["attempts"] = [{"attempt": 2}]
            return super().get_execution_request(root, request)

    fake = FinalAttemptChangingRequests({"state": "completed", "attempts": [{"attempt": 1}]})
    request_dir = _archive_completed_request(tmp_path, request_id, fake)
    result = GatewayPurgeExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
    )
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()


def test_purge_final_fence_blocks_session_lineage_created_during_census(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_lineage_final_boundary"
    session = build_session_record(session_id="ses_lineage_boundary", execution_profile_id="review")
    write_session_record(tmp_path, session)

    class FinalLineageChangingRequests(_ArchiveRequests):
        calls = 0

        def get_execution_request(self, root: Path, request: str) -> dict[str, object]:
            self.calls += 1
            if self.calls == 2:
                record_session_turn(tmp_path, "ses_lineage_boundary", request_id)
            return super().get_execution_request(root, request)

    fake = FinalLineageChangingRequests({"state": "completed"})
    request_dir = _archive_completed_request(tmp_path, request_id, fake)
    result = GatewayPurgeExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
    )
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()


def test_purge_blocks_session_lineage_pin_created_after_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_pinned_after_archive"
    fake = _ArchiveRequests({"state": "completed"})
    request_dir = _archive_completed_request(tmp_path, request_id, fake)
    session = build_session_record(session_id="ses_purge_pin", execution_profile_id="review")
    write_session_record(tmp_path, session)
    record_session_turn(tmp_path, "ses_purge_pin", request_id)

    result = GatewayPurgeExecutor(fake).execute(
        {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
    )
    assert result == {"changed": 0, "blocked": 1}
    assert request_dir.exists()
    archive_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "archive" / request_id
    assert (archive_dir / "archive-manifest.json").is_file()
    # The durable session turn remains available as the continuation
    # authority; a blocked purge must not discard resumable lineage.
    session_path = (
        tmp_path
        / ".audiagentic"
        / "runtime"
        / "agent-execution-gateway"
        / "sessions"
        / "ses_purge_pin"
        / "record.json"
    )
    assert session_path.is_file()


def test_retention_release_requires_explicit_lineage_removal(tmp_path: Path) -> None:
    request_id = "req_release_policy"
    session = build_session_record(session_id="ses_release", execution_profile_id="review")
    write_session_record(tmp_path, session)
    record_session_turn(tmp_path, "ses_release", request_id)

    pinned = request_retention_pin(tmp_path, request_id)
    assert pinned.pinned is True
    assert pinned.reason == "session-lineage-reference"

    session["activity"] = {"request-ids": [], "turn-count": 1}
    write_session_record(tmp_path, session)
    released = request_retention_pin(tmp_path, request_id)
    assert released.pinned is False
    assert released.reason is None


def test_durable_runtime_pin_survives_reload_until_explicit_cleanup(tmp_path: Path) -> None:
    request_id = "req_runtime_release"
    runtime_root = (
        tmp_path
        / ".audiagentic"
        / "runtime"
        / "agent-execution-gateway"
        / request_id
        / "runtime"
    )
    runtime_root.mkdir(parents=True)
    continuation = runtime_root / "provider-session.json"
    continuation.write_text('{"provider-session-id":"opaque-1"}', encoding="utf-8")

    # A fresh read (equivalent to a host restart) still observes the durable pin.
    assert request_retention_pin(tmp_path, request_id).pinned is True
    assert request_retention_pin(tmp_path, request_id).reason == "durable-runtime-root"

    continuation.unlink()
    assert request_retention_pin(tmp_path, request_id).pinned is False


def test_generic_provider_session_release_after_terminal_reload(tmp_path: Path) -> None:
    for profile_id in ("fake", "acp", "mcp-a2a"):
        request_id = f"req_terminal_release_{profile_id}"
        session_id = f"ses_terminal_release_{profile_id}"
        session = build_session_record(session_id=session_id, execution_profile_id=profile_id)
        write_session_record(tmp_path, session)
        record_session_turn(tmp_path, session_id, request_id)
        assert request_retention_pin(tmp_path, request_id).pinned is True

        # Simulate terminal-session persistence/reload followed by explicit
        # lineage release; provider identity does not alter the contract.
        persisted = json.loads((tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "sessions" / session_id / "record.json").read_text(encoding="utf-8"))
        persisted["activity"]["request-ids"] = []
        write_session_record(tmp_path, persisted)
        assert request_retention_pin(tmp_path, request_id).pinned is False


def test_archive_is_provider_neutral_across_execution_profiles(tmp_path: Path) -> None:
    for profile_id in ("fake", "acp", "mcp-a2a"):
        request_id = f"req_archive_profile_{profile_id}"
        request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
        request_dir.mkdir(parents=True)
        (request_dir / "record.json").write_text(
            json.dumps({"state": "completed", "execution-profile-id": profile_id}), encoding="utf-8"
        )
        fake = _ArchiveRequests({"state": "completed", "execution-profile-id": profile_id})
        result = GatewayArchiveExecutor(fake).execute(
            {"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}}
        )
        assert result == {"changed": 1, "blocked": 0}


def test_purge_is_provider_neutral_across_execution_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    for profile_id in ("fake", "acp", "mcp-a2a"):
        request_id = f"req_purge_profile_{profile_id}"
        request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
        request_dir.mkdir(parents=True)
        (request_dir / "record.json").write_text(
            json.dumps({"state": "completed", "execution-profile-id": profile_id}), encoding="utf-8"
        )
        fake = _ArchiveRequests({"state": "completed", "execution-profile-id": profile_id})
        GatewayArchiveExecutor(fake).execute(
            {"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}}
        )
        time.sleep(0.02)
        result = GatewayPurgeExecutor(fake).execute(
            {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
        )
        assert result == {"changed": 1, "blocked": 0}


def test_purge_blocks_linked_lineage_across_provider_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    for profile_id in ("fake", "acp", "mcp-a2a"):
        request_id = f"req_purge_linked_{profile_id}"
        session_id = f"ses_purge_linked_{profile_id}"
        session = build_session_record(session_id=session_id, execution_profile_id=profile_id)
        write_session_record(tmp_path, session)
        request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
        request_dir.mkdir(parents=True)
        (request_dir / "record.json").write_text(json.dumps({"state": "completed"}), encoding="utf-8")
        fake = _ArchiveRequests({"state": "completed"})
        GatewayArchiveExecutor(fake).execute(
            {"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}}
        )
        record_session_turn(tmp_path, session_id, request_id)
        time.sleep(0.02)
        result = GatewayPurgeExecutor(fake).execute(
            {"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}}
        )
        assert result == {"changed": 0, "blocked": 1}
        assert request_dir.exists()


def test_lineage_mutation_fence_is_provider_neutral(tmp_path: Path) -> None:
    for profile_id in ("fake", "acp", "mcp-a2a"):
        request_id = f"req_lineage_mutation_{profile_id}"
        session_id = f"ses_lineage_mutation_{profile_id}"
        session = build_session_record(session_id=session_id, execution_profile_id=profile_id)
        write_session_record(tmp_path, session)
        assert request_retention_pin(tmp_path, request_id).pinned is False
        record_session_turn(tmp_path, session_id, request_id)
        assert request_retention_pin(tmp_path, request_id).pinned is True
        session = json.loads(
            (tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "sessions" / session_id / "record.json").read_text(encoding="utf-8")
        )
        session["activity"]["request-ids"] = []
        write_session_record(tmp_path, session)
        assert request_retention_pin(tmp_path, request_id).pinned is False


def test_purge_after_explicit_lineage_release_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_path = tmp_path / "machine-policy.json"
    _enabled_retention_policy(policy_path)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    request_id = "req_purge_after_release"
    session_id = "ses_purge_after_release"
    session = build_session_record(session_id=session_id, execution_profile_id="acp")
    write_session_record(tmp_path, session)
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    fake = _ArchiveRequests({"state": "completed"})
    GatewayArchiveExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id]}})
    record_session_turn(tmp_path, session_id, request_id)
    session["activity"] = {"request-ids": [], "turn-count": 1}
    write_session_record(tmp_path, session)
    time.sleep(0.02)
    result = GatewayPurgeExecutor(fake).execute({"scope": {"project-root": str(tmp_path), "request-ids": [request_id], "retention-policy": load_retention_policy().snapshot}})
    assert result == {"changed": 1, "blocked": 0}
