from __future__ import annotations

import gzip
import json

import pytest
from audiagentic.components.agents.gateway import observability, replay
from audiagentic.components.agents.agents_paths import gateway_observation_artifact_dir
from audiagentic.components.agents.gateway.evidence_projection import project_public_gateway_evidence
from audiagentic.components.agents.gateway.observation_projection import append_transport_observation
from audiagentic.foundation.transports.agent_session import (
    CorrelationQuality,
    TransportObservation,
    TransportObservationKind,
)


def test_observation_journal_is_redacted_coalesced_and_ordered(tmp_path):
    first = observability.append_observation(
        tmp_path,
        "req_obs",
        session_id="ses_1",
        turn_id="turn_1",
        poll_seq=1,
        dom_signals={"stop-control": True, "cookie": "secret-cookie"},
        response_identity={"assistant-id": "asst_1", "response-text": "do not persist"},
        activity={"label": "thinking"},
    )
    second = observability.append_observation(
        tmp_path,
        "req_obs",
        session_id="ses_1",
        turn_id="turn_1",
        poll_seq=2,
        dom_signals={"stop-control": True, "cookie": "secret-cookie"},
        response_identity={"assistant-id": "asst_1", "response-text": "do not persist"},
        activity={"label": "thinking"},
        monotonic_ms=first["monotonic_ms"] + 25,
    )
    assert (first["event_seq"], second["event_seq"]) == (1, 2)
    assert second["event"] == "observation-coalesced"
    assert second["coalesced"]["repeat_count"] == 2
    raw = observability.read_observation_page(tmp_path, "req_obs", limit=10)
    encoded = json.dumps(raw)
    assert "secret-cookie" not in encoded
    assert "do not persist" not in encoded
    assert raw["items"][0]["facts"]["dom-signals"]["stop-control"] is True


def test_transport_timing_completion_diagnostics_reach_journal_and_public_evidence(tmp_path):
    observation = TransportObservation(
        ag_session_id="ses_timing",
        turn_id="turn_timing",
        sequence=7,
        kind=TransportObservationKind.TIMING,
        observed_at="2026-10-15T00:00:00Z",
        correlation_quality=CorrelationQuality.REQUEST_SCOPED,
        attributes={
            "timing-event": "response-decision",
            "diagnostic-signature": "diag-1",
            "diagnostic-details": json.dumps({
                "completion-gates": {"completion-satisfied": True, "terminal-witness-present": True},
                "completion-matched": ["assistant-bound", "stable-output"],
            }),
        },
    )
    append_transport_observation(tmp_path, "req_timing", observation, session_id="ses_timing")
    item = observability.read_observation_page(tmp_path, "req_timing")["items"][0]
    diagnostic = item["facts"]["diagnostic-facts"]
    assert diagnostic["completion-gates"]["completion-satisfied"] is True
    assert diagnostic["completion-matched"] == ["assistant-bound", "stable-output"]
    public = project_public_gateway_evidence({"observations": {"items": [item]}})
    assert public["observations"]["items"][0]["facts"]["diagnostic-facts"]["completion-matched"] == [
        "assistant-bound", "stable-output"
    ]


def test_unchanged_polls_are_periodically_coalesced(tmp_path):
    for poll in range(1, 11):
        observability.append_observation(
            tmp_path,
            "req_coalesce",
            poll_seq=poll,
            dom_signals={"stop-control": True},
        )
    page = observability.read_observation_page(tmp_path, "req_coalesce", limit=100)
    assert page["count"] <= 3
    assert page["items"][-1]["event"] == "observation-coalesced"
    assert page["items"][-1]["coalesced"]["repeat_count"] == 10
    assert page["items"][-1]["coalesced"]["last_poll_seq"] == 10

def test_terminal_force_flush_persists_final_gap_after_unchanged_coalescing(tmp_path):
    first = observability.append_observation(
        tmp_path, "req_final_gap", poll_seq=1, dom_signals={"stable": True}
    )
    observability.append_observation(
        tmp_path, "req_final_gap", poll_seq=2, dom_signals={"stable": True}
    )
    final = observability.append_observation(
        tmp_path, "req_final_gap", poll_seq=3, dom_signals={"stable": True},
        decision={"outcome": "terminal"}, force_flush=True,
    )
    page = observability.read_observation_page(tmp_path, "req_final_gap", limit=10)
    assert first["event_seq"] == 1
    assert final["event_seq"] == 3
    assert page["count"] == 3
    assert page["items"][-1]["facts"]["decision"]["outcome"] == "terminal"

def test_observation_cursor_is_finite_and_opaque(tmp_path):
    for poll in range(1, 4):
        observability.append_observation(tmp_path, "req_page", poll_seq=poll, dom_signals={"poll": poll})
    page = observability.read_observation_page(tmp_path, "req_page", limit=2)
    assert page["count"] == 2
    assert page["has_more"] is True
    assert page["next_cursor"]
    next_page = observability.read_observation_page(
        tmp_path, "req_page", limit=2, cursor=page["next_cursor"]
    )
    assert [item["event_seq"] for item in next_page["items"]] == [3]
    assert next_page["has_more"] is False


def test_large_observation_tail_cursor_and_summary_reads_are_bounded(tmp_path, monkeypatch):
    for poll in range(1, 141):
        observability.append_observation(
            tmp_path, "req_large", poll_seq=poll, dom_signals={"poll": poll}
        )
    tail = observability.read_observation_page(tmp_path, "req_large", tail=2)
    assert [item["event_seq"] for item in tail["items"]] == [139, 140]

    first_page = observability.read_observation_page(tmp_path, "req_large", limit=2)
    def fail_full_scan(_path):
        raise AssertionError("bounded indexed read unexpectedly scanned the journal")
    monkeypatch.setattr(observability, "iter_ndjson", fail_full_scan)
    next_page = observability.read_observation_page(
        tmp_path, "req_large", limit=2, cursor=first_page["next_cursor"]
    )
    assert [item["event_seq"] for item in next_page["items"]] == [3, 4]

    calls = []
    monkeypatch.setattr(observability, "iter_ndjson", lambda path: (calls.append(path) or iter([{"event_seq": 1}])))
    summary = observability.observation_summary(tmp_path, "req_large")
    assert summary["count"] == 140
    assert summary["last_event_seq"] == 140
    assert len(calls) == 1


def test_optional_artifact_is_bounded_redacted_and_purgeable(tmp_path):
    metadata = observability.capture_redacted_artifact(
        tmp_path,
        "req_artifact",
        {"role": "main", "token": "secret", "children": [{"text": "safe"}], "labels": ["raw prompt/DOM text"]},
    )
    artifact_dir = gateway_observation_artifact_dir(tmp_path, "req_artifact")
    artifact = next(artifact_dir.glob("*.json.gz"))
    decoded = json.loads(gzip.decompress(artifact.read_bytes()))
    assert "token" not in decoded
    assert decoded.get("children", [{}])[0].get("text") is None
    assert "raw prompt/DOM text" not in decoded.get("labels", [])
    assert metadata["compressed_bytes"] == artifact.stat().st_size
    assert observability.purge_observation_artifacts(tmp_path, "req_artifact") == 2
    assert not artifact_dir.exists()


def test_artifact_ttl_is_enforced_by_evidence_reads(tmp_path):
    observability.capture_redacted_artifact(
        tmp_path, "req_expiring", {"role": "main"}, ttl_seconds=1
    )
    manifest = gateway_observation_artifact_dir(tmp_path, "req_expiring") / "manifest.ndjson"
    row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
    row["expires_at_epoch"] = 0
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
    observability.observation_summary(tmp_path, "req_expiring")
    assert not list(gateway_observation_artifact_dir(tmp_path, "req_expiring").glob("*.json.gz"))
    assert not (gateway_observation_artifact_dir(tmp_path, "req_expiring") / "manifest.ndjson").exists()

def test_recovery_intent_fences_ambiguous_submission_and_replay(tmp_path):
    rejected = replay.prepare_recovery_action(
        tmp_path,
        "req_recovery",
        action_attempt_id="attempt_1",
        action="continue",
        action_kind="provider-native-continue",
        attempt_epoch=2,
        retry_budget=2,
        submission_proven=True,
        binding={"project-id": "project", "session-id": "session", "prompt-fingerprint": "fp"},
    )
    assert rejected["disposition"] == "reconciliation-required"
    assert replay.prepare_recovery_action(
        tmp_path,
        "req_recovery",
        action_attempt_id="attempt_1",
        action="continue",
        attempt_epoch=2,
        retry_budget=2,
        submission_proven=True,
    ) == rejected
    safe = replay.prepare_recovery_action(
        tmp_path,
        "req_recovery",
        action_attempt_id="attempt_2",
        action="continue",
        attempt_epoch=2,
        retry_budget=1,
        submission_proven=False,
    )
    assert safe["disposition"] == "intent-persisted"
    replay.record_recovery_result(
        tmp_path, "req_recovery", action_attempt_id="attempt_2", outcome="success"
    )
    result = replay.replay_request(tmp_path, "req_recovery", observations=[])
    assert result["safe-to-resubmit"] is False
    assert result["duplicate-prompt-fence"] == "ambiguous-action-attempt"


def test_native_continuation_fence_persists_intent_before_provider_action(tmp_path):
    from audiagentic.components.agents.gateway.session.dispatch import (
        _prepare_native_recovery_fence,
    )
    from audiagentic.components.agents.gateway.session.sessions_store import (
        build_session_record,
        write_session_record,
    )
    write_session_record(
        tmp_path,
        build_session_record(
            session_id="session",
            execution_profile_id="gpt-auto",
            provider_id="gpt-auto",
            provider_session_ref="chat",
            surface_id="chatgpt-web",
            provider_metadata={
                "project-id": "project",
                "project-url": "https://chatgpt.com/g/g-p-project/project",
                "provider-session-id": "chat",
                "unresolved-turn-id": "turn",
                "prompt-text-digest": "fp",
                "assistant-message-id": "assistant",
                "terminal-evidence": {"terminal-witness-id": "assistant"},
            },
        ),
    )

    _prepare_native_recovery_fence(
        tmp_path,
        "req_native",
        {
            "request-id": "req_native",
            "project-id": "project",
            "session-id": "session",
            "attempt-epoch": 1,
            "prompt-digest": "fp",
            "provider-metadata": {
                "provider-session-id": "chat",
                "unresolved-turn-id": "turn",
                "prompt-text-digest": "fp",
                "assistant-before-message-id": "assistant",
                "assistant-message-id": "assistant",
                "terminal-evidence": {"terminal-witness-id": "assistant", "kind": "terminal"},
                "submission-proven": False,
            },
            "recovery": {"max-attempts": 2, "attempt": 0},
        },
        session_id="session",
    )
    page = replay.read_recovery_page(tmp_path, "req_native", limit=10)
    assert page["items"][0]["action-kind"] == "provider-native-continue"
    assert page["items"][0]["disposition"] == "intent-persisted"
    assert page["items"][0]["retry-budget"] == 2

def test_native_fence_never_synthesizes_terminal_witness_from_assistant(tmp_path):
    from audiagentic.components.agents.gateway.session.dispatch import _prepare_native_recovery_fence
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.components.agents.gateway.session.sessions_store import build_session_record, write_session_record
    write_session_record(tmp_path, build_session_record(
        session_id="session", execution_profile_id="gpt-auto", provider_id="gpt-auto",
        provider_session_ref="chat", surface_id="chatgpt-web",
        provider_metadata={
            "project-id": "project", "provider-session-id": "chat", "unresolved-turn-id": "turn",
            "prompt-text-digest": "fp", "assistant-message-id": "assistant",
            "terminal-evidence": {"terminal-witness-id": "assistant"},
        },
    ))
    with pytest.raises(AudiaGenticError) as raised:
        _prepare_native_recovery_fence(tmp_path, "req_missing_witness", {
            "request-id": "req_missing_witness", "project-id": "project", "session-id": "session",
            "attempt-epoch": 1, "prompt-digest": "fp", "provider-metadata": {
                "provider-session-id": "chat", "unresolved-turn-id": "turn", "prompt-text-digest": "fp",
                "assistant-before-message-id": "assistant", "assistant-message-id": "assistant",
                "terminal-evidence": {"kind": "terminal"}, "submission-proven": False,
            }, "recovery": {"max-attempts": 2, "attempt": 0},
        }, session_id="session")
    assert raised.value.code == "CON-AGW-156"

def test_turn_correlation_requires_boundary_and_terminal_witness():
    proof = replay.prove_turn_correlation(
        {
            "project-id": "project",
            "session-id": "session",
            "chat-id": "chat",
            "turn-id": "turn",
            "prompt-fingerprint": "fp",
        },
        project_id="project",
        session_id="session",
        chat_id="chat",
        turn_id="turn",
        prompt_fingerprint="fp",
        assistant_id="assistant",
        assistant_pinned=True,
        assistant_remounted=False,
        terminal_witness_id="assistant",
    )
    assert proof["strong"] is True
    weak = replay.prove_turn_correlation(
        {
            "project-id": "project",
            "session-id": "session",
            "chat-id": "chat",
            "turn-id": "turn",
            "prompt-fingerprint": "fp",
        },
        project_id="project",
        session_id="session",
        chat_id="chat",
        turn_id="turn",
        prompt_fingerprint="fp",
        assistant_id="assistant",
        assistant_pinned=True,
        assistant_remounted=False,
        terminal_witness_id=None,
    )
    assert weak["strong"] is False
