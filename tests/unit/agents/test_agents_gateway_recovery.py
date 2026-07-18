from __future__ import annotations

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
