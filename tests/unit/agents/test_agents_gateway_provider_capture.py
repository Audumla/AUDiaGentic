from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway import api
from audiagentic.components.agents.gateway.session import sessions as session_runtime_module
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.agents_paths import gateway_admitted_prompt_path


def test_complete_execution_from_provider_persists_correlated_response(monkeypatch, tmp_path: Path):
    record = {
        "request-id": "req_capture",
        "state": "running",
        "revision": 7,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "provider-session-id": "conversation",
            "prompt-message-id": "prompt-1",
            "assistant-message-id": "fallback-assistant-0",
        },
    }
    snapshot = SimpleNamespace(
        latest_assistant_text="captured answer",
        latest_user_text="request",
        latest_user_id="prompt-1",
        latest_assistant_id="assistant-1",
        terminal_witness_assistant_id="assistant-1",
        generating=False,
        dom_signals=frozenset({"completion-control", "more-actions-menu"}),
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


def test_complete_execution_from_provider_uses_prompt_text_for_synthetic_ids(monkeypatch, tmp_path: Path):
    prompt = "synthetic prompt"
    request_id = "req_synthetic"
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 2,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "prompt-digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "provider-session-id": "conversation",
            "prompt-message-id": "fallback-user-0",
            "assistant-message-id": "fallback-assistant-0",
        },
    }
    prompt_path = gateway_admitted_prompt_path(tmp_path, request_id)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    refs = (
        SimpleNamespace(role="user", sequence=0, text=prompt, correlation_text=prompt),
        SimpleNamespace(role="assistant", sequence=1, text="answer", correlation_text="answer"),
    )
    snapshot = SimpleNamespace(
        latest_assistant_text="answer",
        latest_user_text=prompt,
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
