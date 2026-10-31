from __future__ import annotations

import json
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.helpers.gateway_settings import use_gateway_settings
from tests.unit.foundation.test_journal_segments import DAY, append

from audiagentic.components.agents.agents_paths import gateway_request_dir
from audiagentic.components.agents.gateway import (
    journal_retention,
    observability,
    replay,
    retention,
    store,
)
from audiagentic.components.agents.gateway.operations.retention_policy import load_retention_policy
from audiagentic.foundation.io import iter_ndjson
from audiagentic.foundation.observability import journal_segments as segments


def request(root: Path, *, state="completed", **extra):
    directory = gateway_request_dir(root, "req_trace")
    directory.mkdir(parents=True)
    record = {"request-id": directory.name, "state": state, **extra}
    (directory / "record.json").write_text(json.dumps(record), encoding="utf-8")
    output = directory / "output" / "final-response.txt"
    output.parent.mkdir()
    output.write_text("final response", encoding="utf-8")
    path = directory / "observations.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))
    return directory, path


def test_default_five_day_cleanup_only_removes_trace_segments(tmp_path, monkeypatch):
    directory, path = request(tmp_path)
    result = journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=6))
    assert result["segments-deleted"] == 2
    assert list(iter_ndjson(path)) == []
    assert (directory / "record.json").is_file()
    assert (directory / "output" / "final-response.txt").read_text() == "final response"


@pytest.mark.parametrize(
    "fields",
    [
        {"state": "running"},
        {"recovery-required": True},
        {"diagnostics": {"resolution-state": "unresolved"}},
        {"diagnostics": {"resolution-state": "reconciliation-requested"}},
        {"terminal-finalization": {"pending": True}},
    ],
)
def test_protected_requests_keep_all_old_evidence(tmp_path, fields):
    _, path = request(tmp_path, **fields)
    result = journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))
    assert result["segments-deleted"] == 0
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2]
    assert all(source.suffix == ".gz" for source in segments.segment_paths(path))


def test_pinned_request_and_unknown_record_fail_closed(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.session import retention as pins

    directory, path = request(tmp_path)
    monkeypatch.setattr(
        pins, "_request_retention_pin_unlocked", lambda *_: SimpleNamespace(pinned=True)
    )
    assert (
        journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))[
            "segments-deleted"
        ]
        == 0
    )
    (directory / "record.json").write_text("corrupt", encoding="utf-8")
    assert (
        journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))[
            "segments-deleted"
        ]
        == 0
    )
    assert len(list(iter_ndjson(path))) == 2


def test_idle_requests_expire_without_another_provider_append(tmp_path):
    _, path = request(tmp_path)
    result = journal_retention.maintain_project_journals(
        tmp_path, now=DAY + timedelta(days=5, hours=12)
    )
    assert result["segments-deleted"] == 1
    assert [row["event_seq"] for row in iter_ndjson(path)] == [2]


def test_observation_ids_do_not_restart_after_all_raw_trace_expires(tmp_path):
    _, path = request(tmp_path)
    journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))
    assert list(iter_ndjson(path)) == []
    event = observability.append_observation(tmp_path, "req_trace", force_flush=True)
    assert event["event_seq"] == 3


@pytest.mark.parametrize("value", [0, -1, True, "five", 3651])
def test_invalid_policy_disables_expiry(tmp_path, monkeypatch, value):
    use_gateway_settings(monkeypatch, tmp_path, retention={"journal_retention_days": value})
    assert load_retention_policy().policy_id == "invalid"
    _, path = request(tmp_path)
    assert (
        journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))[
            "segments-deleted"
        ]
        == 0
    )
    assert len(list(iter_ndjson(path))) == 2


def test_configured_days_are_independent_of_history_count(tmp_path, monkeypatch):
    use_gateway_settings(monkeypatch, tmp_path, retention={"journal_retention_days": 10, "request_history_limit": 7})
    assert load_retention_policy().journal_retention_days == 10
    assert load_retention_policy().request_history_limit == 7
    assert journal_retention.journal_retention_days() == 10


def test_observation_sequence_and_pagination_span_size_rotation_and_gzip(tmp_path, monkeypatch):
    use_gateway_settings(monkeypatch, tmp_path, retention={"observation_max_bytes": 1000})
    for number in range(5):
        observability.append_observation(
            tmp_path,
            "req_observe",
            poll_seq=number,
            dom_signals={"text-length": number},
            force_flush=True,
        )
    path = gateway_request_dir(tmp_path, "req_observe") / "observations.ndjson"
    assert segments.segment_paths(path)
    first = observability.read_observation_page(tmp_path, "req_observe", limit=2)
    segments.maintain_segments(path, delete_before=None)
    second = observability.read_observation_page(
        tmp_path, "req_observe", limit=2, cursor=first["next_cursor"]
    )
    third = observability.read_observation_page(
        tmp_path, "req_observe", limit=2, cursor=second["next_cursor"]
    )
    assert [r["event_seq"] for page in (first, second, third) for r in page["items"]] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert [
        r["event_seq"]
        for r in observability.read_observation_page(tmp_path, "req_observe", tail=2)["items"]
    ] == [4, 5]


def test_recovery_intent_sequence_and_pagination_survive_rotation(tmp_path, monkeypatch):
    use_gateway_settings(monkeypatch, tmp_path, retention={"recovery_max_bytes": 80})
    for number in range(5):
        replay._append(
            tmp_path, "req_recover", {"event": "action-intent", "action-attempt-id": str(number)}
        )
    first = replay.read_recovery_page(tmp_path, "req_recover", limit=2)
    path = gateway_request_dir(tmp_path, "req_recover") / "recovery-actions.ndjson"
    segments.maintain_segments(path, delete_before=None)
    second = replay.read_recovery_page(
        tmp_path, "req_recover", limit=2, cursor=first["next-cursor"]
    )
    third = replay.read_recovery_page(
        tmp_path, "req_recover", limit=2, cursor=second["next-cursor"]
    )
    assert [r["event-seq"] for page in (first, second, third) for r in page["items"]] == [
        1,
        2,
        3,
        4,
        5,
    ]


def test_timeline_history_and_latest_transition_span_segments(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.store._shared import record_gateway_timeline

    use_gateway_settings(monkeypatch, tmp_path, retention={"timeline_max_bytes": 400})
    monkeypatch.setattr(retention, "schedule_request_retention", lambda *_a, **_kw: True)
    for number in range(5):
        record_gateway_timeline(tmp_path, "req_history", f"step-{number}", state="running")
    first = store.transition_history_page(tmp_path, "req_history", limit=2)
    second = store.transition_history_page(
        tmp_path, "req_history", limit=2, cursor=first["next-cursor"]
    )
    assert [r["event"] for r in first["items"] + second["items"]] == [
        "step-0",
        "step-1",
        "step-2",
        "step-3",
    ]
    assert store.latest_transition_projection(tmp_path, "req_history")["event"] == "step-4"


def test_background_observation_never_resurrects_a_purged_request(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import journal_retention as maintenance

    monkeypatch.setattr(retention, "enforce_request_retention", lambda *_: {})
    monkeypatch.setattr(maintenance, "maintain_project_journals", lambda *_: {})
    monkeypatch.setattr(
        observability,
        "append_observation",
        lambda *_a, **_kw: pytest.fail("recreated purged request"),
    )
    with retention._RETENTION_SCHEDULER_LOCK:
        retention._RETENTION_PENDING[str(tmp_path)] = (tmp_path, "req_purged")
        retention._RETENTION_WORKER_RUNNING = True
    retention._drain_request_retention()
    assert not gateway_request_dir(tmp_path, "req_purged").exists()


def test_host_periodic_scheduling_uses_existing_async_worker(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.service import host, known_projects

    monkeypatch.setattr(
        known_projects,
        "load_known_projects",
        lambda *_: SimpleNamespace(projects=(SimpleNamespace(project_root=tmp_path / "project"),)),
    )
    queued = []
    monkeypatch.setattr(retention, "schedule_request_retention", lambda root: queued.append(root))
    fake = SimpleNamespace(service_store=SimpleNamespace(root=tmp_path))
    host.GatewayServiceHost.schedule_journal_maintenance(fake)
    assert queued == [tmp_path / "project"]


@pytest.mark.parametrize("resolved", [False, True])
def test_durable_recovery_intent_is_protected_until_terminal_resolution(tmp_path, resolved):
    directory, path = request(tmp_path)
    recovery = directory / "recovery-actions.ndjson"
    rows = [
        {
            "event": "action-intent",
            "action-attempt-id": "action-1",
            "disposition": "intent-persisted",
        }
    ]
    if resolved:
        rows.append(
            {
                "event": "action-result",
                "action-attempt-id": "action-1",
                "outcome": "reconciliation-completed",
                "terminal": True,
            }
        )
    recovery.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    result = journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))
    assert bool(result["segments-deleted"]) is resolved
    assert bool(list(iter_ndjson(path))) is not resolved


@pytest.mark.parametrize("state", ["active", "closed"])
def test_session_trace_expiry_requires_terminal_state(tmp_path, state):
    from audiagentic.components.agents.agents_paths import gateway_session_dir

    directory = gateway_session_dir(tmp_path, "ses_test")
    directory.mkdir(parents=True)
    (directory / "record.json").write_text(
        json.dumps({"session-id": directory.name, "state": state, "activity": {"request-ids": []}}),
        encoding="utf-8",
    )
    path = directory / "timeline.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))
    result = journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))
    assert bool(result["segments-deleted"]) is (state == "closed")
    assert (directory / "record.json").is_file()


def test_policy_tool_reports_effective_age_without_paths(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.management_api import gateway_get_retention_policy

    use_gateway_settings(monkeypatch, tmp_path, retention={"journal_retention_days": 8})
    result = gateway_get_retention_policy(tmp_path)
    assert result["journal-retention-days"] == 8
    assert result["journal-rotation"] == "daily-utc-and-size"
    assert str(tmp_path) not in json.dumps(result)


def test_resolved_recovery_control_state_never_expires_with_raw_traces(tmp_path):
    directory, _ = request(tmp_path)
    path = directory / "recovery-actions.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))
    journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=20))
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2]
    assert all(source.suffix == ".gz" for source in segments.segment_paths(path))


def test_policy_is_rechecked_after_eligibility_census(tmp_path, monkeypatch):
    use_gateway_settings(monkeypatch, tmp_path, retention={"journal_retention_days": 5})
    _, path = request(tmp_path)
    real_eligible = journal_retention._eligible_record

    def change_policy(*args, **kwargs):
        result = real_eligible(*args, **kwargs)
        use_gateway_settings(monkeypatch, tmp_path, retention={"journal_retention_days": 20})
        return result

    monkeypatch.setattr(journal_retention, "_eligible_record", change_policy)
    result = journal_retention.maintain_project_journals(tmp_path, now=DAY + timedelta(days=6))
    assert result["segments-deleted"] == 0
    assert len(list(iter_ndjson(path))) == 2


def test_delayed_sweep_cannot_recreate_a_request_purged_during_maintenance(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import api
    from audiagentic.components.agents.gateway.session import sessions_store

    session_id, request_id = "ses_late_sweep", "req_late_sweep"
    monkeypatch.setattr(retention, "schedule_request_retention", lambda *_a, **_kw: True)
    session = sessions_store.build_session_record(
        session_id=session_id, execution_profile_id="test"
    )
    session["activity"]["request-ids"] = [request_id]
    sessions_store.write_session_record(tmp_path, session)
    sessions_store.transition_session_record(
        tmp_path, session_id, "closed", updates={"close-reason": "client-request"}
    )
    store.write_record(
        tmp_path,
        store.build_record(
            request_id=request_id,
            execution_profile_id="test",
            prompt_body="test",
            session_id=session_id,
        ),
    )
    store.transition_record(tmp_path, request_id, "running")
    store.transition_record(tmp_path, request_id, "completed")
    started, release = threading.Event(), threading.Event()

    def paused_sweep(*_args):
        started.set()
        assert release.wait(10)
        return {}

    monkeypatch.setattr(retention, "enforce_request_retention", paused_sweep)
    monkeypatch.setattr(journal_retention, "maintain_project_journals", lambda *_: {})
    monkeypatch.setattr(retention, "_RETENTION_PENDING", {str(tmp_path): (tmp_path, request_id)})
    monkeypatch.setattr(retention, "_RETENTION_WORKER_RUNNING", True)
    worker = threading.Thread(target=retention._drain_request_retention)
    worker.start()
    try:
        assert started.wait(3)
        assert api.purge_execution_session(tmp_path, session_id)["outcome"] == "purged"
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert not gateway_request_dir(tmp_path, request_id).exists()
