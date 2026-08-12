from __future__ import annotations

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.queue.dispatch import diagnose_activity_lease


def test_activity_diagnostic_delegates_to_fenced_nonterminal_transition(tmp_path):
    record = store.build_record(execution_profile_id="default", prompt_body="x")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service", expected_revision=0)
    running = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="service", worker_id="worker", expected_revision=claimed["revision"])
    expired = dict(running)
    expired["activity-lease-expires-at"] = "2000-01-01T00:00:00Z"
    store.write_record(tmp_path, expired)

    diagnosed = diagnose_activity_lease(tmp_path, expired)

    assert diagnosed["state"] == "running"
    assert diagnosed["watchdog-state"] == "intervention"


def test_activity_diagnostic_then_owned_terminal_preserves_verified_stall_classification(tmp_path):
    record = store.build_record(execution_profile_id="default", prompt_body="stall")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service", expected_revision=0)
    running = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="service", worker_id="worker", expected_revision=claimed["revision"])
    expired = dict(running)
    expired["activity-lease-expires-at"] = "2000-01-01T00:00:00Z"
    store.write_record(tmp_path, expired)
    diagnosed = diagnose_activity_lease(tmp_path, expired)
    terminal = store.transition_owned_terminal(
        tmp_path,
        record["request-id"],
        "failed",
        owner_epoch="service",
        worker_id="worker",
        attempt_epoch=1,
        updates={"error": {"code": "INT-AGW-STALL", "details": {"watchdog-classification": "verified-stall"}}},
    )
    assert diagnosed["watchdog-state"] == "intervention"
    assert terminal["terminal-classification"] == "verified-stall"
