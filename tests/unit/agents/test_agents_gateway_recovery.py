from __future__ import annotations

import threading
from pathlib import Path

import pytest

from audiagentic.components.agents import agents_gateway_api as api
from audiagentic.components.agents import agents_gateway_recovery as recovery
from audiagentic.components.agents import agents_gateway_store as store


def test_gateway_api_does_not_expose_second_recovery_authority() -> None:
    assert not hasattr(api, "reconcile_gateway_state")


def _record(project_root: Path, prompt: str = "hello") -> dict:
    record = store.build_record(agent_profile_id="default", prompt_body=prompt)
    store.write_record(project_root, record)
    return record


def test_active_work_index_records_and_clears_on_owned_terminal(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    claimed = store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="epoch-a",
        expected_revision=record["revision"],
        service_root=service_root,
    )
    assert store.active_work_path(service_root, record["request-id"]).exists()
    running = store.start_owned_attempt(
        project_root,
        record["request-id"],
        owner_epoch="epoch-a",
        worker_id="worker-a",
        expected_revision=claimed["revision"],
    )
    terminal = store.transition_owned_terminal(
        project_root,
        record["request-id"],
        "interrupted",
        owner_epoch="epoch-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
        updates={"recovery": {"reason": "service-restart", "outcome": "resubmit-required"}},
    )

    assert terminal["state"] == "interrupted"
    assert not store.active_work_path(service_root, record["request-id"]).exists()


def test_recovery_releases_stale_queued_claim(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    recovered = store.read_record(project_root, record["request-id"])

    assert report.replay_required == 1
    assert recovered["state"] == "interrupted"
    assert recovered["replay-required"] is True
    assert recovered["replay-reason"] == "gateway-recovered-without-work-payload"
    assert recovered["error"]["code"] == "CON-AGW-102"
    assert recovered["recovery"]["outcome"] == "replay-required"
    assert not store.active_work_path(service_root, record["request-id"]).exists()


def test_recovery_interrupts_stale_running_claim_and_acknowledges_cancel(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    claimed = store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )
    store.start_owned_attempt(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        worker_id="worker-a",
        expected_revision=claimed["revision"],
    )
    store.mark_cancel_requested(project_root, record["request-id"])

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    recovered = store.read_record(project_root, record["request-id"])

    assert report.interrupted == 1
    assert recovered["state"] == "interrupted"
    assert recovered["error"]["code"] == "CON-AGW-084"
    assert recovered["cancel-acknowledged-by"] == "recovery"
    assert not store.active_work_path(service_root, record["request-id"]).exists()


def test_cancel_acknowledgement_is_first_writer_wins(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store.mark_cancel_requested(tmp_path, record["request-id"])

    first = store.acknowledge_cancel(tmp_path, record["request-id"], by="queue-worker")
    second = store.acknowledge_cancel(tmp_path, record["request-id"], by="session-runtime")

    assert first["cancel-acknowledged-by"] == "queue-worker"
    assert second["cancel-acknowledged-by"] == "queue-worker"


def test_recovery_discards_malformed_active_work_without_touching_requests(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    active_root = service_root / store.ACTIVE_WORK_DIR
    active_root.mkdir(parents=True)
    (active_root / "not-json.json").write_text("{ definitely not json", encoding="utf-8")
    (active_root / "wrong-shape.json").write_text("[]", encoding="utf-8")
    before = store.read_record(project_root, record["request-id"])

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="epoch-live")
    after = store.read_record(project_root, record["request-id"])

    assert report.quarantined == 2
    assert report.examined == 0
    assert after["revision"] == before["revision"]
    quarantine_dir = active_root / "quarantine"
    assert quarantine_dir.exists()
    assert len(list(quarantine_dir.glob("*.json"))) == 2


def test_recovery_ignores_missing_request_but_keeps_evidence(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    active_root = service_root / store.ACTIVE_WORK_DIR
    active_root.mkdir(parents=True)
    missing_id = "req_missing"
    store.record_active_work(service_root, tmp_path / "missing-project", missing_id, owner_epoch="old")

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new")

    assert report.examined == 1
    assert report.cleared == 0
    assert store.active_work_path(service_root, missing_id).exists()


def test_recovery_is_idempotent_after_releasing_stale_claim(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )

    first = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    second = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    recovered = store.read_record(project_root, record["request-id"])

    assert first.replay_required == 1
    assert second == recovery.RecoveryReport()
    assert recovered["state"] == "interrupted"
    assert recovered["replay-required"] is True


def test_recovery_report_has_no_requeued_attribute() -> None:
    """C6: recovery report uses replay_required, not requeued."""
    assert not hasattr(recovery.RecoveryReport(), "requeued")
    assert hasattr(recovery.RecoveryReport(), "replay_required")


def test_recovery_stale_queued_is_interrupted_with_replay_metadata(tmp_path: Path) -> None:
    """C6: stale queued record becomes interrupted with replay-required=true and CON-AGW-102."""
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    recovered = store.read_record(project_root, record["request-id"])

    assert report.replay_required == 1
    assert recovered["state"] == "interrupted"
    assert recovered["replay-required"] is True
    assert recovered["replay-reason"] == "gateway-recovered-without-work-payload"
    assert recovered["error"]["code"] == "CON-AGW-102"
    assert recovered["recovery"]["outcome"] == "replay-required"
    assert not store.active_work_path(service_root, record["request-id"]).exists()


def test_recovery_stale_running_has_replay_metadata(tmp_path: Path) -> None:
    """C6: stale running record becomes interrupted with CON-AGW-084 and replay-required=False."""
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    claimed = store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )
    store.start_owned_attempt(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        worker_id="worker-a",
        expected_revision=claimed["revision"],
    )

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    recovered = store.read_record(project_root, record["request-id"])

    assert report.interrupted == 1
    assert recovered["state"] == "interrupted"
    assert recovered["error"]["code"] == "CON-AGW-084"
    assert not store.active_work_path(service_root, record["request-id"]).exists()


def test_recovery_idempotent_terminal_does_not_change_outcome(tmp_path: Path) -> None:
    """C6: second recovery pass skips terminal records without changing state."""
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )

    first_report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    recovered_after_first = store.read_record(project_root, record["request-id"])
    first_revision = recovered_after_first["revision"]

    second_report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    recovered_after_second = store.read_record(project_root, record["request-id"])

    assert first_report.replay_required == 1
    assert second_report.examined == 0
    assert recovered_after_second["revision"] == first_revision
    assert recovered_after_second["state"] == "interrupted"


def test_link_replay_sets_replayed_by_on_old_request(tmp_path: Path) -> None:
    """C6: link_replay sets replayed-by-request-id on the old terminal request."""
    project_root = tmp_path / "project"
    record = _record(project_root)
    store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=tmp_path / "service",
    )

    recovery.recover_gateway_requests(tmp_path / "service", live_owner_epoch="new-epoch")

    new_request_id = store.generate_request_id()
    linked = store.link_replay(project_root, record["request-id"], new_request_id=new_request_id)

    assert linked["replayed-by-request-id"] == new_request_id
    assert linked["state"] == "interrupted"


def test_link_replay_fails_for_non_terminal(tmp_path: Path) -> None:
    """C6: link_replay rejects linking to a non-terminal request."""
    project_root = tmp_path / "project"
    record = _record(project_root)

    from audiagentic.foundation.contracts.errors import AudiaGenticError

    with pytest.raises(AudiaGenticError, match="CON-AGW-103"):
        store.link_replay(project_root, record["request-id"], new_request_id="req_new")


def test_link_replay_fails_for_terminal_without_replay_required(tmp_path: Path) -> None:
    """C6: replay linkage is only valid for interrupted records requiring replay."""
    project_root = tmp_path / "project"
    record = _record(project_root)
    terminal = store.transition_record(
        project_root,
        record["request-id"],
        "rejected",
        updates={
            "error": {"code": "CON-AGW-084", "kind": "agents", "message": "failed"},
            "finished-at": "2026-01-01T00:00:00Z",
        },
    )

    from audiagentic.foundation.contracts.errors import AudiaGenticError

    assert terminal["state"] == "rejected"
    with pytest.raises(AudiaGenticError, match="CON-AGW-103"):
        store.link_replay(project_root, record["request-id"], new_request_id="req_new")


def test_recovery_no_pending_queue_entry_after_model_b(tmp_path: Path) -> None:
    """C6: after Model B recovery, no in-memory queue entry exists for the interrupted request."""
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )

    recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")

    recovered = store.read_record(project_root, record["request-id"])
    assert recovered["state"] == "interrupted"
    assert not store.active_work_path(service_root, record["request-id"]).exists()


def test_recovery_report_counts_no_requeued(tmp_path: Path) -> None:
    """C6: recovery report uses replay_required count, not requeued."""
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    store.claim_dispatch(
        project_root,
        record["request-id"],
        owner_epoch="old-epoch",
        expected_revision=record["revision"],
        service_root=service_root,
    )

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")
    assert report.replay_required == 1
    assert not hasattr(report, "requeued")


def test_c7_malformed_entry_quarantined_not_deleted(tmp_path: Path) -> None:
    """C7: malformed active-work entry is quarantined rather than deleted."""
    service_root = tmp_path / "service"
    project_root = tmp_path / "project"
    record = _record(project_root)
    active_root = service_root / store.ACTIVE_WORK_DIR
    active_root.mkdir(parents=True)

    # Write a malformed entry with invalid JSON
    (active_root / "malformed.json").write_text("{bad json", encoding="utf-8")
    # Write an entry missing required fields
    (active_root / "missing_fields.json").write_text(
        '{"request-id": "req_123"}',  # missing project-root
        encoding="utf-8",
    )

    report = recovery.recover_gateway_requests(service_root, live_owner_epoch="live")

    assert report.quarantined == 2
    quarantine_dir = active_root / "quarantine"
    assert quarantine_dir.exists()
    quarantined_files = list(quarantine_dir.glob("*.json"))
    assert len(quarantined_files) == 2
    # Verify the original malformed files are gone from the active dir
    assert not (active_root / "malformed.json").exists()
    assert not (active_root / "missing_fields.json").exists()
    # The original request record is untouched
    assert store.read_record(project_root, record["request-id"]) is not None


def test_c7_clear_active_work_non_throwing(tmp_path: Path) -> None:
    """C7: clear_active_work does not throw even for missing paths."""
    service_root = tmp_path / "service"
    # Should not raise even if the entry doesn't exist
    store.clear_active_work(service_root, "nonexistent_request_id")


def test_cancel_acknowledgement_race_has_one_winner(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store.mark_cancel_requested(tmp_path, record["request-id"])
    winners: list[str] = []

    def acknowledge(name: str) -> None:
        winners.append(
            store.acknowledge_cancel(tmp_path, record["request-id"], by=name)["cancel-acknowledged-by"]
        )

    # Closed actor vocabulary (C10): race real component names, not arbitrary strings.
    actors = ["queue-worker", "session-runtime", "dispatch", "recovery"] * 3
    threads = [threading.Thread(target=acknowledge, args=(actor,)) for actor in actors]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    final = store.read_record(tmp_path, record["request-id"])
    assert len(set(winners)) == 1
    assert final["cancel-acknowledged-by"] == winners[0]
