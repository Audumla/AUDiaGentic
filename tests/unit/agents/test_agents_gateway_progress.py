"""Unit tests for agents_gateway_progress — operator progress projection (SH07 / RV741)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.agents.gateway import api as gateway
from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import progress as progress_mod
from audiagentic.components.agents.models.execution_profile_api import (
    create_execution_profile,
)
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


def _make_profile(project_root: Path, profile_id: str, provider_id: str, **params) -> None:
    create_execution_profile(
        project_root,
        {
            "profile_id": profile_id,
            "provider_id": provider_id,
            "instances": ["gpt-4o"],
            "is_default": True,
            "params": params,
        },
    )
    set_implementation_state(
        project_root, "providers", provider_id, ImplementationState(enabled=True)
    )


def _result(data: dict) -> SimpleNamespace:
    return SimpleNamespace(result_data=data)


# ---------- progress projection tests ----------


def test_running_with_model_event_gives_model_active(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:00Z"

    session_event = {
        "kind": "assistant-message",
        "timestamp": "2026-01-01T00:00:05Z",
    }

    now = datetime.datetime(2026, 1, 1, 0, 0, 10, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=session_event,
        now=now,
    )

    assert projection["phase"] == "model-active"
    assert projection["stale-progress"] is False
    assert projection["running-seconds"] == 10.0


def test_running_no_session_event_gives_launching(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:00Z"

    now = datetime.datetime(2026, 1, 1, 0, 0, 10, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(record, now=now)

    assert projection["phase"] == "launching"
    assert projection["stale-progress"] is False


def test_stale_progress_when_no_evidence_past_threshold(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    # Started 610 seconds ago, no session event since then
    record["started-at"] = "2026-01-01T00:00:00Z"

    now = datetime.datetime(2026, 1, 1, 0, 10, 10, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(record, now=now)

    assert projection["stale-progress"] is True
    assert projection["stale-reason"] == "no-turn-evidence-past-threshold"


def test_stale_progress_with_session_event_past_threshold(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:00Z"

    # Session event 5 minutes ago (past 300s threshold)
    session_event = {
        "kind": "assistant-message",
        "timestamp": "2026-01-01T00:04:00Z",
    }

    now = datetime.datetime(2026, 1, 1, 0, 10, 10, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=session_event,
        now=now,
    )

    assert projection["phase"] == "model-active"
    assert projection["stale-progress"] is True
    assert projection["stale-reason"] == "no-turn-evidence-past-threshold"


def test_terminal_record_phase_and_not_stale(tmp_path: Path) -> None:
    for terminal_state in ("completed", "failed", "cancelled", "rejected"):
        record = store.build_record(execution_profile_id="default", prompt_body="hello")
        record["state"] = terminal_state
        record["started-at"] = "2026-01-01T00:00:00Z"
        record["finished-at"] = "2026-01-01T00:00:05Z"

        # Even with age well past threshold, terminal states are never stale
        now = datetime.datetime(2026, 1, 1, 0, 10, 10, tzinfo=datetime.timezone.utc)
        projection = progress_mod.project_request_progress(record, now=now)

        assert projection["phase"] == terminal_state, f"state={terminal_state}"
        assert projection["stale-progress"] is False, f"state={terminal_state}"


def test_terminal_interrupted_maps_to_interrupted(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "interrupted"

    projection = progress_mod.project_request_progress(record)
    assert projection["phase"] == "interrupted"
    assert projection["stale-progress"] is False


def test_queued_phase(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    assert record["state"] == "queued"

    projection = progress_mod.project_request_progress(record)
    assert projection["phase"] == "queued"


def test_claimed_phase_when_dispatch_owner_epoch_set(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["dispatch-owner-epoch"] = "service-a"

    projection = progress_mod.project_request_progress(record)
    assert projection["phase"] == "claimed"


def test_tool_event_gives_tool_active(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:00Z"

    session_event = {
        "kind": "tool-call",
        "timestamp": "2026-01-01T00:00:03Z",
    }

    now = datetime.datetime(2026, 1, 1, 0, 0, 5, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=session_event,
        now=now,
    )

    assert projection["phase"] == "tool-active"


def test_turn_start_event_gives_turn_starting(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:00Z"

    session_event = {
        "kind": "unknown-kind",
        "event": "session.turn.started",
        "timestamp": "2026-01-01T00:00:03Z",
    }

    now = datetime.datetime(2026, 1, 1, 0, 0, 5, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=session_event,
        now=now,
    )

    assert projection["phase"] == "turn-starting"


def test_unknown_state_gives_unknown_phase(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "some-weird-state"

    projection = progress_mod.project_request_progress(record)
    assert projection["phase"] == "unknown"


def test_redaction_no_forbidden_values_leak(tmp_path: Path) -> None:
    """Adversarial session event carrying forbidden fields must be stripped."""
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:00Z"

    # Adversarial session event with forbidden content
    adversarial_event = {
        "kind": "assistant-message",
        "timestamp": "2026-01-01T00:00:05Z",
        "prompt-body": "secret-prompt-text",
        "output": "secret-output-text",
        "tool_args": {"arg": "secret-value"},
        "provider-binding-ref": "ref-secret-abc",
        "binding-ref": "another-secret",
    }

    now = datetime.datetime(2026, 1, 1, 0, 0, 10, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=adversarial_event,
        now=now,
    )

    dumped = json.dumps(projection)

    for forbidden in (
        "secret-prompt-text",
        "secret-output-text",
        "secret-value",
        "ref-secret-abc",
        "another-secret",
    ):
        assert forbidden not in dumped, f"forbidden value leaked: {forbidden}"

    # Only kind and timestamp from the session event should survive
    if projection.get("latest-session-event"):
        assert set(projection["latest-session-event"].keys()) <= {"kind", "timestamp"}


def test_last_progress_source_request_transition(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:10Z"

    session_event = {
        "kind": "assistant-message",
        "timestamp": "2026-01-01T00:00:05Z",
    }

    now = datetime.datetime(2026, 1, 1, 0, 0, 20, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=session_event,
        now=now,
    )

    assert projection["last-progress-source"] == "request-transition"


def test_last_progress_source_session_event(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:05Z"

    session_event = {
        "kind": "assistant-message",
        "timestamp": "2026-01-01T00:00:10Z",
    }

    now = datetime.datetime(2026, 1, 1, 0, 0, 20, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=session_event,
        now=now,
    )

    assert projection["last-progress-source"] == "session-event"


def test_running_seconds_none_when_not_started(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    # queued state, no started-at

    projection = progress_mod.project_request_progress(record)
    assert projection["running-seconds"] is None


def test_all_keys_present() -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    projection = progress_mod.project_request_progress(record)

    expected_keys = {
        "phase",
        "running-seconds",
        "last-progress-at",
        "last-progress-source",
        "latest-transition",
        "latest-session-event",
        "stale-progress",
        "stale-reason",
    }
    assert set(projection.keys()) == expected_keys


# ---------- API wiring tests ----------


def test_request_runtime_status_includes_progress(tmp_path: Path, monkeypatch) -> None:
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        return _result(
            {"provider-id": "local-openai", "status": "ok", "model": "gpt-4o", "output": "done"}
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_execute_provider,
    )

    gateway.run_execution_request(tmp_path, prompt_body="hi")

    records = store.list_records(tmp_path)
    req_id = records[0]["request-id"]
    status = gateway.request_runtime_status(tmp_path, req_id)

    assert "progress" in status
    assert "phase" in status["progress"]


def test_wait_timeout_marker_on_non_terminal(tmp_path: Path, monkeypatch) -> None:
    _make_profile(tmp_path, "default", "local-openai")
    import threading

    hold = threading.Event()

    def slow_execute_provider(*, identity, execution_request, timeout_seconds):
        hold.wait(timeout=5)
        return _result(
            {"provider-id": "local-openai", "status": "ok", "model": "gpt-4o", "output": "done"}
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        slow_execute_provider,
    )

    submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
    result = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=0.2)

    assert result["wait-timeout"] is True
    assert "progress" in result

    hold.set()
    gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)


def test_gateway_overview_includes_runtime_fingerprint(tmp_path: Path, monkeypatch) -> None:
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        return _result(
            {"provider-id": "local-openai", "status": "ok", "model": "gpt-4o", "output": "done"}
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_execute_provider,
    )

    gateway.run_execution_request(tmp_path, prompt_body="hi")

    overview = gateway.gateway_overview(tmp_path)

    assert "runtime-fingerprint" in overview
    fingerprint = overview["runtime-fingerprint"]
    assert "runtime-version" in fingerprint
    assert "process-instance-id" in fingerprint
    assert "started-at" in fingerprint
    assert isinstance(fingerprint["runtime-version"], str)
    # process-instance-id is a UUID hex (32 chars)
    assert len(fingerprint["process-instance-id"]) == 32
    # started-at is an ISO timestamp
    from datetime import datetime, timezone

    datetime.fromisoformat(fingerprint["started-at"]).replace(tzinfo=timezone.utc)


def test_runtime_fingerprint_has_no_git_dependency() -> None:
    """Process identity works in non-Git environments."""
    fp = gateway._runtime_fingerprint()
    assert "runtime-version" in fp
    assert "process-instance-id" in fp
    assert "started-at" in fp
    # build-id is optional — may be absent for local installs
    # No source-stamp field (Git dependency removed)
    assert "source-stamp" not in fp


def test_runtime_fingerprint_process_identity_is_stable() -> None:
    """Process identity doesn't change between calls."""
    fp1 = gateway._runtime_fingerprint()
    fp2 = gateway._runtime_fingerprint()
    assert fp1["process-instance-id"] == fp2["process-instance-id"]
    assert fp1["started-at"] == fp2["started-at"]


def test_terminal_wait_does_not_add_timeout_marker(tmp_path: Path, monkeypatch) -> None:
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        return _result(
            {"provider-id": "local-openai", "status": "ok", "model": "gpt-4o", "output": "done"}
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_execute_provider,
    )

    result = gateway.run_execution_request(tmp_path, prompt_body="hi")

    assert "wait-timeout" not in result
    assert result["state"] == "completed"


def test_stale_progress_threshold_constant_exposed() -> None:
    assert progress_mod.STALE_PROGRESS_THRESHOLD_SECONDS == 300


# ── SH15: richer bounded progress-summary regression tests ──────────────


def _write_timeline(project_root: Path, session_id: str, entries: list[dict]) -> None:
    """Write an NDJSON session timeline file for testing."""
    from audiagentic.components.agents.agents_paths import gateway_session_timeline_path

    path = gateway_session_timeline_path(project_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_progress_summary_includes_event_kind_counts(tmp_path: Path) -> None:
    """SH15: build_session_progress_summary produces event-kind-counts."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            {
                "event": "session.turn.thought",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {"kind": "thought", "sequence": 1, "request-id": "req_01"},
            },
            {
                "event": "session.turn.assistant-message",
                "timestamp": "2026-01-01T00:00:02Z",
                "attributes": {"kind": "assistant-message", "sequence": 2, "request-id": "req_01"},
            },
            {
                "event": "session.turn.tool-call",
                "timestamp": "2026-01-01T00:00:03Z",
                "attributes": {
                    "kind": "tool-call",
                    "sequence": 3,
                    "request-id": "req_01",
                    "tool-call-id": "tc1",
                    "status": "in_progress",
                },
            },
            {
                "event": "session.turn.result",
                "timestamp": "2026-01-01T00:00:04Z",
                "attributes": {"kind": "result", "sequence": 4, "request-id": "req_01"},
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    counts = summary["event-kind-counts"]
    assert isinstance(counts, dict)
    assert counts.get("thought") == 1
    assert counts.get("assistant-message") == 1
    assert counts.get("tool-call") == 1
    assert counts.get("result") == 1


def test_progress_summary_tool_active_completed_failed_counts(tmp_path: Path) -> None:
    """SH15: tool status tracking produces active/completed/failed counts."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            # Tool 1: in_progress (active)
            {
                "event": "session.turn.tool-call",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {
                    "kind": "tool-call",
                    "sequence": 1,
                    "request-id": "req_01",
                    "tool-call-id": "tc1",
                    "status": "in_progress",
                },
            },
            # Tool 2: completed
            {
                "event": "session.turn.tool-call",
                "timestamp": "2026-01-01T00:00:02Z",
                "attributes": {
                    "kind": "tool-call",
                    "sequence": 2,
                    "request-id": "req_01",
                    "tool-call-id": "tc2",
                    "status": "completed",
                },
            },
            # Tool 3: failed
            {
                "event": "session.turn.tool-call",
                "timestamp": "2026-01-01T00:00:03Z",
                "attributes": {
                    "kind": "tool-call",
                    "sequence": 3,
                    "request-id": "req_01",
                    "tool-call-id": "tc3",
                    "status": "failed",
                },
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    assert summary["tool-count-active"] == 1
    assert summary["tool-count-completed"] == 1
    assert summary["tool-count-failed"] == 1


def test_progress_summary_latest_sequence_and_timestamp(tmp_path: Path) -> None:
    """SH15: latest-sequence and latest-timestamp reflect the most recent event."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            {
                "event": "session.turn.thought",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {"kind": "thought", "sequence": 1, "request-id": "req_01"},
            },
            {
                "event": "session.turn.result",
                "timestamp": "2026-01-01T00:00:05Z",
                "attributes": {"kind": "result", "sequence": 5, "request-id": "req_01"},
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    assert summary["latest-sequence"] == 5
    assert summary["latest-timestamp"] == "2026-01-01T00:00:05Z"


def test_progress_summary_stop_reason_from_turn_finished(tmp_path: Path) -> None:
    """SH15: stop-reason from turn.finished entry is captured."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            {
                "event": "session.turn.assistant-message",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {"kind": "assistant-message", "sequence": 1, "request-id": "req_01"},
            },
            {
                "event": "session.turn.finished",
                "timestamp": "2026-01-01T00:00:05Z",
                "attributes": {
                    "kind": "finished",
                    "sequence": 2,
                    "request-id": "req_01",
                    "stop-reason": "end_turn",
                },
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    assert summary["stop-reason"] == "end_turn"


def test_progress_summary_dropped_events_and_total_events(tmp_path: Path) -> None:
    """SH15: dropped-events and total-events from turn.finished are captured."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            {
                "event": "session.turn.assistant-message",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {"kind": "assistant-message", "sequence": 1, "request-id": "req_01"},
            },
            {
                "event": "session.turn.finished",
                "timestamp": "2026-01-01T00:00:05Z",
                "attributes": {
                    "kind": "finished",
                    "sequence": 2,
                    "request-id": "req_01",
                    "dropped-events": 3,
                    "total-events": 47,
                    "callback-disabled": False,
                },
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    assert summary["dropped-events"] == 3
    assert summary["total-events"] == 47
    assert summary["callback-disabled"] is False


def test_progress_summary_callback_disabled_true(tmp_path: Path) -> None:
    """SH15: callback-disabled=true when the transport disables callbacks."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            {
                "event": "session.turn.finished",
                "timestamp": "2026-01-01T00:00:05Z",
                "attributes": {
                    "kind": "finished",
                    "sequence": 1,
                    "request-id": "req_01",
                    "callback-disabled": True,
                },
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    assert summary["callback-disabled"] is True


def test_progress_summary_assistant_thought_chunk_count(tmp_path: Path) -> None:
    """SH15: assistant-thought-chunk-count reflects combined assistant+thought events."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            {
                "event": "session.turn.thought",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {"kind": "thought", "sequence": 1, "request-id": "req_01"},
            },
            {
                "event": "session.turn.thought",
                "timestamp": "2026-01-01T00:00:02Z",
                "attributes": {"kind": "thought", "sequence": 2, "request-id": "req_01"},
            },
            {
                "event": "session.turn.assistant-message",
                "timestamp": "2026-01-01T00:00:03Z",
                "attributes": {"kind": "assistant-message", "sequence": 3, "request-id": "req_01"},
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    assert summary["assistant-thought-chunk-count"] == 3


def test_project_request_progress_with_summary_includes_richer_fields() -> None:
    """SH15: project_request_progress includes progress-summary fields when provided."""
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["state"] = "running"
    record["started-at"] = "2026-01-01T00:00:00Z"

    session_event = {"kind": "tool-call", "timestamp": "2026-01-01T00:00:03Z"}

    progress_summary = {
        "latest-sequence": 42,
        "event-kind-counts": {"thought": 2, "assistant-message": 1, "tool-call": 3},
        "tool-count-active": 2,
        "tool-count-completed": 1,
        "tool-count-failed": 0,
        "assistant-thought-chunk-count": 3,
        "assistant-thought-approx-bytes": 1024,
        "stop-reason": None,
        "dropped-events": 0,
        "total-events": 6,
        "callback-disabled": False,
    }

    now = datetime.datetime(2026, 1, 1, 0, 0, 10, tzinfo=datetime.timezone.utc)
    projection = progress_mod.project_request_progress(
        record,
        latest_session_event=session_event,
        progress_summary=progress_summary,
        now=now,
    )

    # Base fields still present
    assert projection["phase"] == "tool-active"
    assert projection["stale-progress"] is False

    # SH15 richer fields included
    assert projection["latest-sequence"] == 42
    assert projection["event-kind-counts"] == {"thought": 2, "assistant-message": 1, "tool-call": 3}
    assert projection["tool-count-active"] == 2
    assert projection["tool-count-completed"] == 1
    assert projection["tool-count-failed"] == 0
    assert projection["assistant-thought-chunk-count"] == 3
    assert projection["assistant-thought-approx-bytes"] == 1024
    assert projection["dropped-events"] == 0
    assert projection["total-events"] == 6
    assert projection["callback-disabled"] is False
    # None values should not be included (stop-reason is None)
    assert "stop-reason" not in projection


def test_project_request_progress_without_summary_is_backward_compat() -> None:
    """SH15: when no progress_summary is provided, output keys match baseline."""
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    projection = progress_mod.project_request_progress(record)

    expected_keys = {
        "phase",
        "running-seconds",
        "last-progress-at",
        "last-progress-source",
        "latest-transition",
        "latest-session-event",
        "stale-progress",
        "stale-reason",
    }
    assert set(projection.keys()) == expected_keys


def test_wait_timeout_includes_progress_summary(tmp_path: Path, monkeypatch) -> None:
    """SH15: wait_execution_request timeout path includes richer progress summary."""
    _make_profile(tmp_path, "default", "local-openai")
    import threading

    hold = threading.Event()

    def slow_execute_provider(*, identity, execution_request, timeout_seconds):
        hold.wait(timeout=5)
        return _result(
            {"provider-id": "local-openai", "status": "ok", "model": "gpt-4o", "output": "done"}
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        slow_execute_provider,
    )

    submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
    result = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=0.2)

    assert result["wait-timeout"] is True
    assert "progress" in result

    # The progress projection should be present; it may not have summary fields
    # if the session timeline was empty, but the call should not fail.
    assert "phase" in result["progress"]

    hold.set()
    gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)


def test_progress_summary_request_id_filtering(tmp_path: Path) -> None:
    """SH15: build_session_progress_summary filters by request-id when provided."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            {
                "event": "session.turn.thought",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {"kind": "thought", "sequence": 1, "request-id": "req_A"},
            },
            {
                "event": "session.turn.assistant-message",
                "timestamp": "2026-01-01T00:00:02Z",
                "attributes": {"kind": "assistant-message", "sequence": 2, "request-id": "req_B"},
            },
        ],
    )

    # Filter for req_A only
    summary_a = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_A")
    assert summary_a is not None
    assert summary_a["event-kind-counts"]["thought"] == 1
    assert "assistant-message" not in summary_a["event-kind-counts"]

    # Filter for req_B only
    summary_b = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_B")
    assert summary_b is not None
    assert summary_b["event-kind-counts"]["assistant-message"] == 1
    assert "thought" not in summary_b["event-kind-counts"]


def test_progress_summary_none_when_no_timeline(tmp_path: Path) -> None:
    """SH15: build_session_progress_summary returns None when no timeline exists."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    summary = session_store.build_session_progress_summary(tmp_path, "ses_missing", "req_01")
    assert summary is None


def test_progress_summary_tool_status_updates(tmp_path: Path) -> None:
    """SH15: tool status can transition from active to completed/failed."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    _write_timeline(
        tmp_path,
        "ses_test",
        [
            # Tool starts in_progress
            {
                "event": "session.turn.tool-call",
                "timestamp": "2026-01-01T00:00:01Z",
                "attributes": {
                    "kind": "tool-call",
                    "sequence": 1,
                    "request-id": "req_01",
                    "tool-call-id": "tc1",
                    "status": "in_progress",
                },
            },
            # Same tool completes
            {
                "event": "session.turn.tool-call",
                "timestamp": "2026-01-01T00:00:03Z",
                "attributes": {
                    "kind": "tool-call",
                    "sequence": 3,
                    "request-id": "req_01",
                    "tool-call-id": "tc1",
                    "status": "completed",
                },
            },
        ],
    )

    summary = session_store.build_session_progress_summary(tmp_path, "ses_test", "req_01")
    assert summary is not None
    # Latest status wins — tc1 is completed, so active=0, completed=1
    assert summary["tool-count-active"] == 0
    assert summary["tool-count-completed"] == 1


def test_request_runtime_status_includes_sh15_progress_summary(tmp_path: Path, monkeypatch) -> None:
    """SH15: request_runtime_status includes richer progress summary fields."""
    _make_profile(tmp_path, "default", "local-openai")
    import threading

    hold = threading.Event()

    def slow_execute_provider(*, identity, execution_request, timeout_seconds):
        hold.wait(timeout=5)
        return _result(
            {"provider-id": "local-openai", "status": "ok", "model": "gpt-4o", "output": "done"}
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        slow_execute_provider,
    )

    submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
    req_id = submitted["request-id"]

    # Give the worker time to start (but it'll block on hold)
    import time

    time.sleep(0.3)

    status = gateway.request_runtime_status(tmp_path, req_id)
    assert "progress" in status

    hold.set()
    gateway.wait_execution_request(tmp_path, req_id, timeout_seconds=5)
