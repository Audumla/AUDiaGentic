"""SH32-C: the SESSION_PURGE operation - policy snapshot, selection, dispositions, replay."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.agents_paths import gateway_session_dir
from audiagentic.components.agents.gateway.operations import (
    GatewayOperationExecutor,
    GatewayOperationsApplication,
    GatewaySessionPurgeExecutor,
    ManagementCommand,
    ManagementOperationKind,
    ManagementOperationStore,
)
from audiagentic.components.agents.gateway.operations.retention_policy import load_retention_policy
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from tests.helpers.gateway_settings import use_gateway_settings
from tests.helpers.session_purge import (
    DAY,
    enable_policy,
    link_request,
    make_project,
    make_request,
    make_session,
)


def _scope(root, **extra):
    return {"project-root": str(root), "retention-policy": load_retention_policy().snapshot, **extra}


def _op(root, operation_id="op_1", **extra):
    return {"operation-id": operation_id, "kind": "session-purge", "scope": _scope(root, **extra)}


def _lineage(root, **kwargs):
    session_id = make_session(root, **kwargs)
    link_request(root, session_id, make_request(root, session_id))
    return session_id


@pytest.fixture
def root(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path)
    return make_project(tmp_path)


def test_the_kind_is_part_of_the_closed_vocabulary_and_is_distinct_from_request_purge():
    assert ManagementOperationKind("session-purge") is ManagementOperationKind.SESSION_PURGE
    assert ManagementOperationKind.SESSION_PURGE is not ManagementOperationKind.PURGE


def test_creating_the_operation_snapshots_the_machine_policy_over_any_caller_value(root, tmp_path):
    application = GatewayOperationsApplication(ManagementOperationStore(tmp_path / "service"))
    created = application.create_operation(ManagementCommand(
        "op_snap", ManagementOperationKind.SESSION_PURGE,
        {"project-root": str(root), "retention-policy": {"session-purge-enabled": True, "policy-digest": "forged"}}))
    stored = application._store.read(created["operation-id"])["scope"]["retention-policy"]
    assert stored == load_retention_policy().snapshot and stored["policy-digest"] != "forged"


def test_the_executor_purges_every_eligible_session_and_reports_dispositions(root):
    eligible = _lineage(root)
    young = make_session(root, age=60)
    result = GatewayOperationExecutor(None).execute(_op(root))
    assert (result["purged"], result["blocked"], result["unchanged"]) == (1, 0, 0)
    assert not gateway_session_dir(root, eligible).exists() and gateway_session_dir(root, young).exists()
    assert result["dispositions"] == [{"session-id": eligible, "outcome": "purged"}]
    assert "remote provider conversations are never touched" in result["scope"]
    assert "retention-claim" not in sessions_store.read_session_record(root, young)


def test_explicit_session_ids_report_blocked_and_unchanged_with_reasons(root):
    old = _lineage(root)
    active = make_session(root, state="active")
    result = GatewaySessionPurgeExecutor().execute(_op(root, **{"session-ids": [old, active, "ses_gone"]}))
    outcomes = {item["session-id"]: item for item in result["dispositions"]}
    assert outcomes[old]["outcome"] == "purged"
    assert outcomes[active] == {"session-id": active, "outcome": "blocked", "reason": "session-not-closed"}
    assert outcomes["ses_gone"] == {"session-id": "ses_gone", "outcome": "unchanged", "reason": "session-not-found"}
    assert (result["purged"], result["blocked"], result["unchanged"]) == (1, 1, 1)


def test_a_disabled_or_changed_policy_does_nothing(root, monkeypatch, tmp_path):
    session_id = _lineage(root)
    operation = _op(root)
    use_gateway_settings(monkeypatch, tmp_path, retention={"purge_enabled": False})
    result = GatewaySessionPurgeExecutor().execute(operation)
    assert result["reason"] == "SESSION_PURGE_POLICY_UNAVAILABLE" and result["purged"] == 0
    assert gateway_session_dir(root, session_id).exists()
    enable_policy(monkeypatch, tmp_path, session_purge_inactivity_seconds=2 * DAY)  # a different digest
    assert GatewaySessionPurgeExecutor().execute(operation)["reason"] == "SESSION_PURGE_POLICY_UNAVAILABLE"
    assert gateway_session_dir(root, session_id).exists()


def test_an_explicit_batch_over_the_limit_is_refused_whole(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path, max_batch_size=1)
    root = make_project(tmp_path)
    a, b = _lineage(root), _lineage(root)
    result = GatewaySessionPurgeExecutor().execute(_op(root, **{"session-ids": [a, b]}))
    assert result["reason"] == "SESSION_PURGE_BATCH_LIMIT" and result["purged"] == 0
    assert gateway_session_dir(root, a).exists() and gateway_session_dir(root, b).exists()


def test_a_scan_is_bounded_by_the_batch_size_and_says_so(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path, max_batch_size=1)
    root = make_project(tmp_path)
    _lineage(root), _lineage(root)
    result = GatewaySessionPurgeExecutor().execute(_op(root))
    assert result["purged"] == 1 and result["truncated"] is True


def test_a_replay_of_the_same_operation_resumes_a_crashed_purge(root, monkeypatch):
    from audiagentic.components.agents.gateway.session import lineage_delete

    session_id = _lineage(root)
    real_delete = lineage_delete.delete_session_lineage

    def boom(*_args, **_kwargs):
        raise RuntimeError("crash")

    monkeypatch.setattr(lineage_delete, "delete_session_lineage", boom)
    with pytest.raises(RuntimeError):
        GatewaySessionPurgeExecutor().execute(_op(root))
    claim = sessions_store.read_session_record(root, session_id)["retention-claim"]
    assert claim["stage"] == "deleting" and claim["operation-id"] == "op_1"
    monkeypatch.setattr(lineage_delete, "delete_session_lineage", real_delete)
    # The surviving claim is not eligible for a NEW scan, but the same operation resumes it first.
    result = GatewaySessionPurgeExecutor().execute(_op(root))
    assert result["dispositions"] == [{"session-id": session_id, "outcome": "purged"}]
    assert not gateway_session_dir(root, session_id).exists()


def test_a_different_operation_cannot_take_a_claimed_session(root):
    session_id = _lineage(root)
    sessions_store.claim_retention(root, session_id, operation_id="op_other")
    result = GatewaySessionPurgeExecutor().execute(_op(root, **{"session-ids": [session_id]}))
    assert result["dispositions"] == [{"session-id": session_id, "outcome": "blocked", "reason": "retention-claimed"}]


def test_a_malformed_scope_is_refused(root):
    with pytest.raises(AudiaGenticError):
        GatewaySessionPurgeExecutor().execute(_op(root, **{"session-ids": []}))
    with pytest.raises(AudiaGenticError):
        GatewaySessionPurgeExecutor().execute({"operation-id": "op", "scope": {"retention-policy": {}}})
