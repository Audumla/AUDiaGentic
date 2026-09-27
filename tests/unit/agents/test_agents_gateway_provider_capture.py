from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.agents.gateway import api
from audiagentic.components.agents.gateway.session import sessions as session_runtime_module
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.gateway import output


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
    updated = {**record, "state": "completed", "revision": 8}
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(
        sessions_store,
        "read_session_record",
        lambda *_: {"provider": {"metadata": {}}},
    )
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
    artifact = {
        "artifact-id": "final-response",
        "request-id": "req_capture",
        "media-type": "text/plain",
        "bytes": 15,
        "sha256": "hash",
        "output-preview": "captured answer",
        "output-truncated": False,
    }
    monkeypatch.setattr(output, "persist_final_response", lambda *_: artifact)
    calls = {}

    def transition(*args, **kwargs):
        calls.update(kwargs)
        return updated

    monkeypatch.setattr(api.store, "transition_operator_terminal", transition)
    result = api.complete_execution_from_provider(tmp_path, "req_capture")

    assert result["state"] == "completed"
    assert result["response-artifact"] == {
        "artifact-id": "final-response",
        "request-id": "req_capture",
        "media-type": "text/plain",
        "bytes": 15,
        "sha256": "hash",
    }
    assert calls["expected_revision"] == 7
    assert calls["updates"]["response-artifact"] == result["response-artifact"]
