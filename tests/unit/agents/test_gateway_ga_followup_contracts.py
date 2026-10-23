from __future__ import annotations

import json

from audiagentic.components.agents.gateway import replay
from audiagentic.components.agents.agents_paths import (
    gateway_observation_index_path,
    gateway_timeline_index_path,
    gateway_timeline_path,
)
from audiagentic.components.agents.gateway.evidence_projection import project_public_gateway_evidence
from audiagentic.components.agents.gateway.observation_projection import append_request_projection
from audiagentic.components.agents.gateway.observability import append_observation, observation_summary, read_observation_page
from audiagentic.components.agents.gateway.store import transition_history_page


def test_provider_binding_and_diagnostics_project_into_request_journal(tmp_path):
    event = append_request_projection(
        tmp_path,
        "req_seam",
        {
            "request-id": "req_seam",
            "session-id": "ses_1",
            "turn-id": "turn_1",
            "attempt-epoch": 3,
            "state": "running",
            "provider-metadata": {
                "provider-session-id": "chat_1",
                "assistant-message-id": "assistant_1",
                "submission-proven": False,
                "dom-signals": ["completion-control", "error-alert", "network-error-alert"],
                "secret": "do not persist",
            },
            "diagnostics": {
                "failure-code": "EXT-GPTAUTO-003",
                "side-effect-state": "may-have-started",
                "resolution-state": "unresolved",
            },
        },
        source="provider-binding",
    )
    assert event["source"] == "provider-binding"
    page = read_observation_page(tmp_path, "req_seam")
    item = page["items"][0]
    assert item["facts"]["dom-signals"]["completion-control"] is True
    assert item["facts"]["response-identity"]["assistant-id"] == "assistant_1"
    assert item["facts"]["decision"]["submission-proven"] is False
    assert "do not persist" not in json.dumps(item)


def test_recovery_result_closes_real_action_and_is_journaled(tmp_path):
    replay.prepare_recovery_action(
        tmp_path,
        "req_action",
        action_attempt_id="attempt_1",
        action="resume-existing",
        action_kind="provider-native-continue",
        attempt_epoch=1,
        retry_budget=1,
        submission_proven=False,
    )
    replay.record_recovery_result(
        tmp_path,
        "req_action",
        action_attempt_id="attempt_1",
        outcome="provider-resume-completed",
        terminal=True,
    )
    page = read_observation_page(tmp_path, "req_action", limit=10)
    assert [item["source"] for item in page["items"]] == ["recovery-intent", "recovery-result"]
    assert page["items"][-1]["facts"]["action"]["outcome"] == "provider-resume-completed"


def test_observation_reads_have_index_and_bounded_tail(tmp_path):
    for poll in range(1, 11):
        append_observation(tmp_path, "req_tail", poll_seq=poll, dom_signals={"stop-control": bool(poll % 2)})
    assert gateway_observation_index_path(tmp_path, "req_tail").exists()
    page = read_observation_page(tmp_path, "req_tail", tail=2)
    assert [item["poll_seq"] for item in page["items"]] == [9, 10]


def test_observation_summary_keeps_metadata_and_latest_diagnostic_facts(tmp_path):
    append_observation(
        tmp_path,
        "req_summary",
        poll_seq=4,
        activity={"label": "generating", "group": "provider-work"},
        decision={"completion-satisfied": False},
    )
    append_observation(
        tmp_path,
        "req_summary",
        poll_seq=5,
        response_identity={"terminal": True, "terminal-witness-hash": "witness"},
        decision={"completion-satisfied": True},
        force_flush=True,
    )
    summary = observation_summary(tmp_path, "req_summary")
    assert summary["count"] == 2
    assert summary["first_event_seq"] == 1
    assert summary["last_event_seq"] == 2
    assert summary["last_poll_seq"] == 5
    assert summary["has_more"] is False
    assert summary["latest"]["facts"]["response-identity"]["terminal"] is True

    public = project_public_gateway_evidence({"observation-summary": summary})
    public_summary = public["observation-summary"]
    assert public_summary["count"] == 2
    assert public_summary["last_poll_seq"] == 5
    assert public_summary["latest"]["facts"]["response-identity"]["terminal"] is True


def test_replay_requires_terminal_and_response_witnesses_and_reports_ttfa():
    entries = [
        {"event": "dom-observed", "monotonic_ms": 100, "facts": {"activity": {"label": "generating"}, "error-occurrence": {"code": "E1"}}},
        {"event": "terminal", "monotonic_ms": 175, "facts": {"response-identity": {"terminal": True, "terminal-witness-hash": "w", "response-ref-hash": "r"}, "decision": {"completion-satisfied": True}}},
    ]
    result = replay.replay_observations(entries)
    assert result["completion-evidence"]["completion-proven"] is True
    assert result["outcome-classification"] == "error-later-resolved"
    assert result["time-to-first-response-ms"] == 75

def test_history_cursor_is_independent_and_deterministic(tmp_path):
    timeline = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / "req_history" / "timeline.ndjson"
    timeline.parent.mkdir(parents=True)
    timeline.write_text(
        "".join(json.dumps({"event": f"state-{i}", "state": "running", "timestamp": f"t-{i}"}) + "\n" for i in range(3)),
        encoding="utf-8",
    )
    first = transition_history_page(tmp_path, "req_history", limit=2)
    second = transition_history_page(tmp_path, "req_history", limit=2, cursor=first["next-cursor"])
    assert [item["event"] for item in first["items"]] == ["state-0", "state-1"]
    assert [item["event"] for item in second["items"]] == ["state-2"]


def test_history_deep_cursor_carries_index_offset(tmp_path, monkeypatch):
    timeline = gateway_timeline_path(tmp_path, "req_deep_history")
    index_path = gateway_timeline_index_path(tmp_path, "req_deep_history")
    timeline.parent.mkdir(parents=True)
    lines = []
    index_rows = []
    offset = 0
    for event_index in range(120):
        line = (json.dumps({"event": f"state-{event_index}", "state": "running", "timestamp": f"t-{event_index}"}) + "\n").encode()
        lines.append(line)
        index_rows.append({"event_seq": event_index + 1, "offset": offset, "length": len(line)})
        offset += len(line)
    timeline.write_bytes(b"".join(lines))
    index_path.write_text("".join(json.dumps(row) + "\n" for row in index_rows), encoding="utf-8")

    page = transition_history_page(tmp_path, "req_deep_history", limit=5)
    for _ in range(10):
        page = transition_history_page(tmp_path, "req_deep_history", limit=5, cursor=page["next-cursor"])
    assert [item["event"] for item in page["items"]] == [f"state-{i}" for i in range(50, 55)]
    cursor = json.loads(__import__("base64").urlsafe_b64decode(page["next-cursor"] + "=" * (-len(page["next-cursor"]) % 4)))
    assert cursor["index-offset"] > 0

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.store._records.iter_ndjson",
        lambda _path: (_ for _ in ()).throw(AssertionError("deep indexed history used a full-prefix fallback")),
    )
    next_page = transition_history_page(tmp_path, "req_deep_history", limit=5, cursor=page["next-cursor"])
    assert next_page["items"][0]["event"] == "state-55"


def test_public_evidence_has_one_redaction_and_byte_boundary():
    payload = {
        "schema_version": "gateway-evidence.v1",
        "request-id": "req_public",
        "state": "running",
        "diagnostics": {"classification": "watchdog", "reason-code": "reconcile"},
        "evidence": [{"sequence": i, "phase": "in-progress"} for i in range(100)],
        "observation-summary": {"count": 100, "latest": {"facts": {"message": "raw prompt secret"}}},
        "observations": {"items": [{"event": "dom-observed", "facts": {"text": "raw prompt secret"}} for _ in range(100)]},
        "recovery": {"items": [{"binding": {"prompt-fingerprint": "secret"}, "outcome": "pending"} for _ in range(100)]},
        "history": {"items": [{"event": "state", "state": "running", "timestamp": "t"} for _ in range(100)]},
    }
    result = project_public_gateway_evidence(payload, max_bytes=2048)
    encoded = json.dumps(result)
    assert len(encoded.encode("utf-8")) <= 2048
    assert "raw prompt secret" not in encoded
    assert "prompt-fingerprint" not in encoded


def test_reconnect_classification_is_read_only_and_fail_closed():
    safe = replay.classify_reconnect(
        {"provider-metadata": {"provider-session-id": "chat", "submission-proven": False}}
    )
    ambiguous = replay.classify_reconnect(
        {"provider-metadata": {"provider-session-id": "chat", "submission-proven": True}}
    )
    assert safe["classification"] == "safe-reconnect"
    assert safe["read-only"] is True
    assert ambiguous["classification"] == "reconcile-required"
    response_only_after_restart = replay.classify_reconnect(
        {
            "state": "running",
            "provider-metadata": {
                "unresolved-turn-pending": True,
                "unresolved-turn-id": "turn-response-only",
                "submission-proven": False,
            },
        }
    )
    assert response_only_after_restart["classification"] == "reconcile-required"

def test_replay_uses_canonical_errors_meaningful_activity_and_actual_recovery_outcomes():
    entries = [
        {"monotonic_ms": 100, "facts": {"activity": {"label": "heartbeat"}, "error-occurrence": {"failure-code": "FAIL-1"}}},
        {"monotonic_ms": 150, "facts": {"activity": {"label": "thinking"}}},
        {"monotonic_ms": 175, "facts": {"action": {"outcome": "provider-resume-completed"}}},
        {"monotonic_ms": 176, "facts": {"action": {"outcome": "abandon-accepted"}}},
        {"monotonic_ms": 177, "facts": {"action": {"outcome": "reconciliation-completed"}}},
        {"monotonic_ms": 178, "facts": {"action": {"outcome": "cleared-not-submitted"}}},
        {"event": "terminal", "monotonic_ms": 200, "facts": {"response-identity": {"terminal": True, "terminal-witness-hash": "w", "response-ref-hash": "r"}}},
    ]
    result = replay.replay_observations(entries)
    assert result["first-activity-monotonic-ms"] == 150
    assert result["time-to-first-response-ms"] == 50
    assert result["groups"]["FAIL-1"]["errors"] == 1
    assert result["action-success-count"] == 4
    assert set(result["action-outcomes"]) == {
        "provider-resume-completed", "abandon-accepted", "reconciliation-completed", "cleared-not-submitted"
    }

def test_replay_carries_prior_timing_witnesses_into_terminal_resolution():
    entries = [
        {
            "monotonic_ms": 100,
            "facts": {
                "response-identity": {
                    "terminal-witness-hash": "witness-from-timing",
                    "response-ref-hash": "response-from-timing",
                }
            },
        },
        {
            "event": "terminal",
            "monotonic_ms": 150,
            "facts": {"response-identity": {"terminal": True, "stop-reason": "end_turn"}},
        },
    ]
    result = replay.replay_observations(entries)
    assert result["completion-evidence"]["completion-proven"] is True
    assert result["outcome-classification"] == "completed-with-witness"
