from __future__ import annotations

import threading
from pathlib import Path

from audiagentic.components.agents import agents_gateway_recovery as recovery
from audiagentic.components.agents import agents_gateway_store as store


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

    assert report.requeued == 1
    assert recovered["state"] == "queued"
    assert recovered["dispatch-owner-epoch"] is None


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
    second = store.acknowledge_cancel(tmp_path, record["request-id"], by="session-turn")

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

    assert report.cleared == 2
    assert report.examined == 0
    assert after["revision"] == before["revision"]
    assert not list(active_root.glob("*.json"))


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

    assert first.requeued == 1
    assert second == recovery.RecoveryReport()
    assert recovered["state"] == "queued"
    assert recovered["dispatch-owner-epoch"] is None


def test_cancel_acknowledgement_race_has_one_winner(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store.mark_cancel_requested(tmp_path, record["request-id"])
    winners: list[str] = []

    def acknowledge(name: str) -> None:
        winners.append(
            store.acknowledge_cancel(tmp_path, record["request-id"], by=name)["cancel-acknowledged-by"]
        )

    threads = [threading.Thread(target=acknowledge, args=(f"actor-{i}",)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    final = store.read_record(tmp_path, record["request-id"])
    assert len(set(winners)) == 1
    assert final["cancel-acknowledged-by"] == winners[0]
