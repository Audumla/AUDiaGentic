from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway import api
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.session import sessions as session_runtime_module
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.agents_paths import gateway_admitted_prompt_path


@pytest.mark.parametrize("initial_state", ["running", "failed", "cancelled"])
def test_complete_execution_from_provider_persists_correlated_response(monkeypatch, tmp_path: Path, initial_state: str):
    record = {
        "request-id": "req_capture",
        "state": initial_state,
        "revision": 7,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "provider-session-id": "conversation",
            "prompt-message-id": "prompt-1",
            "assistant-message-id": "fallback-assistant-0",
            "submission-proven": True,
        },
    }
    snapshot = SimpleNamespace(
        latest_assistant_text="captured answer",
        latest_user_text="request",
        latest_user_id="prompt-1",
        latest_assistant_id="assistant-1",
        terminal_witness_assistant_id="assistant-1",
        generating=False,
        # Current ChatGPT project conversations expose the response Copy
        # control but may omit the older response-level More actions menu.
        dom_signals=frozenset({"completion-control"}),
    )
    artifact_ref = {
        "artifact-id": "final-response",
        "request-id": "req_capture",
        "media-type": "text/plain",
        "bytes": 15,
        "sha256": "hash",
    }
    updated = {**record, "state": "completed", "revision": 8, "response-artifact": artifact_ref}
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(
        sessions_store,
        "read_session_record",
        lambda *_: {"provider": {"metadata": {}}},
    )
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: {})
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    calls = {}
    capture_calls = 0

    def capture(*args, **kwargs):
        nonlocal capture_calls
        capture_calls += 1
        return {"outcome": "captured", "snapshot": snapshot}

    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(capture_latest_response=capture),
    )

    def transition(*args, **kwargs):
        calls.update(kwargs)
        return updated

    monkeypatch.setattr(api.store, "transition_operator_terminal", transition)
    result = api.complete_execution_from_provider(tmp_path, "req_capture")

    assert result["state"] == "completed"
    assert result["response-artifact"] == artifact_ref
    assert capture_calls == 2
    assert calls["expected_revision"] == 7
    assert calls["updates"]["__final-response-text"] == "captured answer"


def test_complete_execution_from_provider_rejects_queued_request(monkeypatch, tmp_path: Path):
    record = {
        "request-id": "req_queued",
        "state": "queued",
        "revision": 1,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
    }
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, "req_queued")

    assert getattr(caught.value, "code", None) == "CON-AGW-152"


def test_complete_execution_from_provider_requires_request_submission_proof(monkeypatch, tmp_path: Path):
    record = {
        "request-id": "req_unsubmitted",
        "state": "running",
        "revision": 1,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
    }
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, "req_unsubmitted")

    assert getattr(caught.value, "code", None) == "CON-AGW-157"


def test_complete_execution_from_provider_allows_unresolved_turn_recovery(monkeypatch, tmp_path: Path):
    record = {
        "request-id": "req_unresolved",
        "state": "running",
        "revision": 1,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "unresolved-turn-pending": True,
        },
    }
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {"provider": {"metadata": {}}})
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: {})
    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(capture_latest_response=lambda *_args, **_kwargs: {"outcome": "not-captured", "reason": "test"}),
    )

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, "req_unresolved")

    assert getattr(caught.value, "code", None) == "CON-AGW-154"


def test_complete_execution_from_provider_uses_prompt_text_for_synthetic_ids(monkeypatch, tmp_path: Path):
    prompt = "synthetic prompt"
    request_id = "req_synthetic"
    materialized_prompt = "governed instructions\n\n" + prompt
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 2,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "prompt-digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt-template-digest": hashlib.sha256(materialized_prompt.encode()).hexdigest(),
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "provider-session-id": "conversation",
            "prompt-message-id": "fallback-user-0",
            "assistant-message-id": "fallback-assistant-0",
            "submission-proven": True,
        },
    }
    prompt_path = gateway_admitted_prompt_path(tmp_path, request_id)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_bytes(materialized_prompt.encode("utf-8"))
    refs = (
        SimpleNamespace(role="user", sequence=0, text=materialized_prompt, correlation_text=materialized_prompt),
        SimpleNamespace(role="assistant", sequence=1, text="answer", correlation_text="answer"),
    )
    snapshot = SimpleNamespace(
        latest_assistant_text="answer",
        latest_user_text=materialized_prompt,
        latest_user_id="fallback-user-0",
        latest_assistant_id="fallback-assistant-1",
        terminal_witness_assistant_id="fallback-assistant-1",
        generating=False,
        dom_signals=frozenset({"completion-control", "more-actions-menu"}),
        message_refs=refs,
    )
    artifact_ref = {"artifact-id": "final-response", "request-id": request_id, "media-type": "text/plain", "bytes": 6, "sha256": "hash"}
    calls = {}
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {"provider": {"metadata": {}}})
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: {})
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    monkeypatch.setattr(session_runtime_module, "get_session_runtime", lambda: SimpleNamespace(capture_latest_response=lambda *args, **kwargs: {"outcome": "captured", "snapshot": snapshot}))
    monkeypatch.setattr(api.store, "transition_operator_terminal", lambda *args, **kwargs: (calls.update(kwargs) or {**record, "state": "completed", "response-artifact": artifact_ref}))

    result = api.complete_execution_from_provider(tmp_path, request_id)

    assert result["state"] == "completed"
    assert calls["updates"]["__final-response-text"] == "answer"


def test_complete_execution_from_provider_reports_missing_admitted_snapshot(monkeypatch, tmp_path: Path):
    request_id = "req_missing_snapshot"
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 2,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "prompt-template-digest": "missing",
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "provider-session-id": "conversation",
            "prompt-message-id": "fallback-user-0",
            "submission-proven": True,
        },
    }
    snapshot = SimpleNamespace(
        latest_assistant_text="answer",
        latest_user_text="prompt",
        latest_user_id="fallback-user-0",
        latest_assistant_id="fallback-assistant-1",
        terminal_witness_assistant_id="fallback-assistant-1",
        generating=False,
        dom_signals=frozenset({"completion-control"}),
        message_refs=(),
    )
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {"provider": {"metadata": {}}})
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: {})
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(
            capture_latest_response=lambda *args, **kwargs: {
                "outcome": "captured",
                "snapshot": snapshot,
            }
        ),
    )

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, request_id)

    assert getattr(caught.value, "code", None) == "RES-AGW-112"


def test_reconcile_executes_capture_and_reports_completion(monkeypatch, tmp_path: Path):
    record = {
        "request-id": "req_reconcile",
        "state": "interrupted",
        "revision": 4,
        "diagnostics": {"resolution-state": "unresolved"},
    }
    updated = {
        **record,
        "revision": 5,
        "diagnostics": {"resolution-state": "reconciliation-requested"},
    }
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(api.store, "update_diagnostics", lambda *_args, **_kwargs: updated)
    monkeypatch.setattr(
        api,
        "complete_execution_from_provider",
        lambda *_: {
            "state": "completed",
            "revision": 6,
            "response-artifact": {"artifact-id": "final-response"},
        },
    )

    result = api.recover_execution_request(
        tmp_path, "req_reconcile", action="reconcile", expected_revision=4
    )

    assert result["state"] == "completed"
    assert result["reconciliation"] == {"outcome": "completed"}


def test_reconcile_preserves_failed_request_when_provider_dom_is_unresolved(monkeypatch, tmp_path: Path):
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    record = {
        "request-id": "req_failed",
        "state": "failed",
        "revision": 8,
        "diagnostics": {"resolution-state": "unresolved"},
    }
    updated = {
        **record,
        "revision": 9,
        "diagnostics": {"resolution-state": "reconciliation-requested"},
    }
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(api.store, "update_diagnostics", lambda *_args, **_kwargs: updated)

    def unresolved(*_args, **_kwargs):
        raise AudiaGenticError(
            code="CON-AGW-154",
            kind="agents",
            message="provider response could not be captured",
            details={"reason": "provider-error-page"},
        )

    monkeypatch.setattr(api, "complete_execution_from_provider", unresolved)
    result = api.recover_execution_request(tmp_path, "req_failed", action="reconcile")

    assert result["state"] == "failed"
    assert result["reconciliation"] == {
        "outcome": "unresolved",
        "reason": "CON-AGW-154",
    }
def test_operator_provider_capture_can_complete_bounded_interruption(tmp_path: Path):
    """An interrupted recovery remains eligible for a verified operator capture."""
    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    running = store.transition_record(
        tmp_path,
        record["request-id"],
        "running",
        updates={"started-at": "2026-09-27T00:00:00Z"},
    )
    interrupted = store.transition_record(
        tmp_path,
        record["request-id"],
        "interrupted",
        updates={
            "error": {
                "code": "CON-AGW-084",
                "kind": "agents",
                "message": "bounded recovery exhausted",
            },
            "finished-at": "2026-09-27T00:01:00Z",
        },
    )

    completed = store.transition_operator_terminal(
        tmp_path,
        record["request-id"],
        expected_revision=interrupted["revision"],
        updates={"__final-response-text": "captured answer"},
    )

    assert running["state"] == "running"
    assert completed["state"] == "completed"
    assert completed["response-artifact"]["artifact-id"] == "final-response"


def test_operator_provider_capture_can_promote_failed_request(tmp_path: Path):
    """A failed request remains recoverable when a provider response is proven."""
    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    running = store.transition_record(
        tmp_path,
        record["request-id"],
        "running",
        updates={"started-at": "2026-09-27T00:00:00Z"},
    )
    failed = store.transition_record(
        tmp_path,
        record["request-id"],
        "failed",
        updates={"error": {"code": "EXT-GPTAUTO-001", "message": "provider observation failed"}},
    )

    completed = store.transition_operator_terminal(
        tmp_path,
        record["request-id"],
        expected_revision=failed["revision"],
        updates={"__final-response-text": "captured answer"},
    )

    assert running["state"] == "running"
    assert failed["state"] == "failed"
    assert completed["state"] == "completed"
    assert api.get_execution_response(tmp_path, record["request-id"]) == "captured answer"
