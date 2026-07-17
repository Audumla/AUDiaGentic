from __future__ import annotations

from audiagentic.components.agents import agents_gateway_api as api
from audiagentic.components.agents import agents_gateway_store as store


def test_reconcile_gateway_state_terminalizes_orphaned_records(tmp_path):
    queued = store.build_record(
        request_id="req_queued",
        agent_profile_id="profile-a",
        prompt_body="queued",
    )
    running = store.build_record(
        request_id="req_running",
        agent_profile_id="profile-a",
        prompt_body="running",
    )
    store.write_record(tmp_path, queued)
    store.write_record(tmp_path, running)
    store.transition_record(tmp_path, "req_running", "running")

    result = api.reconcile_gateway_state(tmp_path)

    assert result == {
        "ok": True,
        "reconciled": [
            {"request-id": "req_queued", "state": "rejected"},
            {"request-id": "req_running", "state": "failed"},
        ],
        "reconciled-sessions": [],
    }
    assert store.read_record(tmp_path, "req_queued")["state"] == "rejected"
    assert store.read_record(tmp_path, "req_running")["state"] == "failed"

    second = api.reconcile_gateway_state(tmp_path)

    assert second == {"ok": True, "reconciled": [], "reconciled-sessions": []}


def test_reconcile_marks_orphaned_sessions_failed(tmp_path):
    from audiagentic.components.agents import agents_gateway_sessions_store as session_store

    record = session_store.build_session_record(agent_profile_id="profile-a")
    session_store.write_session_record(tmp_path, record)

    result = api.reconcile_gateway_state(tmp_path)

    assert result["reconciled-sessions"] == [
        {"session-id": record["session-id"], "state": "failed"}
    ]
    stored = session_store.read_session_record(tmp_path, record["session-id"])
    assert stored["state"] == "failed"
    assert stored["close-reason"] == "orphaned"
