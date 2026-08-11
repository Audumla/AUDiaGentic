from __future__ import annotations

import time
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
