from __future__ import annotations

import gzip
import json

from audiagentic.components.agents.gateway import observability, replay
from audiagentic.components.agents.agents_paths import gateway_observation_artifact_dir


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


def test_optional_artifact_is_bounded_redacted_and_purgeable(tmp_path):
    metadata = observability.capture_redacted_artifact(
        tmp_path,
        "req_artifact",
        {"role": "main", "token": "secret", "children": [{"text": "safe"}]},
    )
    artifact_dir = gateway_observation_artifact_dir(tmp_path, "req_artifact")
    artifact = next(artifact_dir.glob("*.json.gz"))
    decoded = json.loads(gzip.decompress(artifact.read_bytes()))
    assert "token" not in decoded
    assert decoded.get("children", [{}])[0].get("text") is None
    assert metadata["compressed_bytes"] == artifact.stat().st_size
    assert observability.purge_observation_artifacts(tmp_path, "req_artifact") == 2
    assert not artifact_dir.exists()


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
