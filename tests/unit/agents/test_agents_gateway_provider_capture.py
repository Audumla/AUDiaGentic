from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.agents_paths import gateway_admitted_prompt_path
from audiagentic.components.agents.gateway import api, store
from audiagentic.components.agents.gateway.session import sessions as session_runtime_module
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import PromptFingerprint
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatMessageRef, ChatSnapshot
from audiagentic.components.providers.contracts.conversation_focus import ConversationCaptureLocator
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.mark.parametrize("artifact_state", ["valid", "missing", "corrupt"])
def test_capture_is_idempotent_when_normal_completion_already_won(tmp_path, monkeypatch, artifact_state):
    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    running = store.transition_record(tmp_path, record["request-id"], "running")
    completed = store.transition_operator_terminal(
        tmp_path, record["request-id"], expected_revision=running["revision"],
        updates={"__final-response-text": "durable winner"},
    )
    def forbidden_runtime():
        raise AssertionError("completed capture must not inspect a newer provider turn")
    monkeypatch.setattr(session_runtime_module, "get_session_runtime", forbidden_runtime)
    if artifact_state != "valid":
        changed = copy.deepcopy(completed)
        if artifact_state == "missing":
            changed["response-artifact"] = None
        else:
            changed["response-artifact"]["sha256"] = "0" * 64
        store.write_record(tmp_path, changed)
        with pytest.raises(Exception) as caught:
            api.complete_execution_from_provider(tmp_path, record["request-id"])
        assert getattr(caught.value, "code", None) == ("RES-AGW-141" if artifact_state == "missing" else "CON-AGW-140")
        return
    result = api.complete_execution_from_provider(tmp_path, record["request-id"])
    assert result["state"] == "completed"
    assert result["capture-source"] == "durable-response"
    assert result["response-artifact"] == completed["response-artifact"]
    assert store.read_record(tmp_path, record["request-id"])["revision"] == completed["revision"]


@pytest.mark.parametrize("changed_conversation", [False, True])
@pytest.mark.parametrize("virtualized", [False, True])
def test_capture_missing_conversation_binding_passes_checkpoint_and_revalidates_url(
    monkeypatch, tmp_path, changed_conversation, virtualized
):
    request_id = "req_target_capture"
    metadata = {
        "target-id": "exact-target", "project-url": "https://chatgpt.com/g/g-p-project/project",
        "prompt-text-digest": PromptFingerprint.from_text("request").digest,
        "unresolved-turn-id": request_id, "unresolved-turn-pending": True,
        "submission-proven": False, "send-intent-ever": True,
        "submission-stage": "send-click-acknowledged",
        "unresolved-baseline-user-count": 0, "unresolved-baseline-assistant-count": 0,
    }
    if virtualized:
        metadata.update({
            "unresolved-baseline-user-count": 5, "unresolved-baseline-assistant-count": 5,
            "unresolved-baseline-user-id": "old-user", "unresolved-baseline-assistant-id": "old-assistant",
        })
    record = {"request-id": request_id, "session-id": "ses_capture", "state": "failed",
              "revision": 7, "resolved-provider-id": "gpt-auto", "provider-metadata": metadata}
    # The request metadata relay can lag the canonical session checkpoint.
    provider = {"id": "gpt-auto", "metadata": {**metadata, "submission-attempt-id": "canonical-attempt"}}
    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/recovered", composer_present=True,
        composer_editable=True, user_count=5 if virtualized else 1, assistant_count=5 if virtualized else 1,
        latest_user_id="user-1", latest_user_text="request", latest_assistant_id="assistant-1",
        latest_assistant_text="answer", terminal_witness_assistant_id="assistant-1",
        error_present=False, generating=False, dom_signals=frozenset({"completion-control"}),
        message_refs=((ChatMessageRef("user", "old-user", "old", 0),
                       ChatMessageRef("assistant", "old-assistant", "old", 1)) if virtualized else ())
        + (ChatMessageRef("user", "user-1", "request", 2),
           ChatMessageRef("assistant", "assistant-1", "answer", 3)),
    )
    calls = []
    writes = []

    def capture(*_args, locator, **_kwargs):
        assert isinstance(locator, ConversationCaptureLocator)
        assert locator.provider_target_id == "exact-target"
        assert locator.prompt_text_digest == metadata["prompt-text-digest"]
        calls.append(locator)
        from dataclasses import replace
        value = replace(snapshot, url="https://chatgpt.com/g/g-p-project/c/other") if changed_conversation and len(calls) == 2 else snapshot
        return {"outcome": "captured", "snapshot": value, "binding": {"chat-url": value.url}}

    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {"provider": provider})
    monkeypatch.setattr(session_runtime_module, "get_session_runtime", lambda: SimpleNamespace(capture_latest_response=capture))
    monkeypatch.setattr(api.store, "transition_operator_terminal", lambda *args, **kwargs: (writes.append(kwargs) or {"state": "completed"}))
    if changed_conversation:
        with pytest.raises(Exception) as caught:
            api.complete_execution_from_provider(tmp_path, request_id)
        assert getattr(caught.value, "code", None) == "CON-AGW-155"
        assert not writes
    else:
        result = api.complete_execution_from_provider(tmp_path, request_id)
        assert result["state"] == "completed"
        assert writes[0]["expected_session_provider"] == provider
        assert writes[0]["updates"]["provider-metadata"]["chat-url"] == snapshot.url
        assert writes[0]["updates"]["provider-metadata"]["submission-attempt-id"] == "canonical-attempt"
        assert writes[0]["updates"]["completion"]["provider-user-message-id"] == "user-1"


@pytest.mark.parametrize("initial_state", ["running", "failed", "cancelled"])
@pytest.mark.parametrize("commit_race", ["none", "activity", "owner", "exhausted"])
def test_complete_execution_from_provider_persists_correlated_response(monkeypatch, tmp_path: Path, initial_state: str, commit_race):
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

    commit_calls = []
    def transition(*args, **kwargs):
        calls.update(kwargs)
        commit_calls.append(kwargs["expected_revision"])
        if commit_race == "exhausted" or (commit_race in {"activity", "owner"} and len(commit_calls) == 1):
            from audiagentic.foundation.contracts.errors import AudiaGenticError
            record["revision"] += 1
            if commit_race == "owner":
                record["worker-id"] = "successor-worker"
            raise AudiaGenticError(code="CON-AGW-071", kind="agents", message="request revision changed")
        return updated

    monkeypatch.setattr(api.store, "transition_operator_terminal", transition)
    if commit_race in {"owner", "exhausted"}:
        with pytest.raises(Exception) as caught:
            api.complete_execution_from_provider(tmp_path, "req_capture")
        assert getattr(caught.value, "code", None) == ("CON-AGW-156" if commit_race == "owner" else "CON-AGW-071")
        assert len(commit_calls) == (1 if commit_race == "owner" else 3)
        assert capture_calls == 2
        return
    result = api.complete_execution_from_provider(tmp_path, "req_capture")

    assert result["state"] == "completed"
    assert result["response-artifact"] == artifact_ref
    assert capture_calls == 2
    assert calls["expected_revision"] == (8 if commit_race == "activity" else 7)
    assert commit_calls == ([7, 8] if commit_race == "activity" else [7])
    assert calls["updates"]["__final-response-text"] == "captured answer"


@pytest.mark.parametrize("variant", ["retained", "missing", "foreign", "branch", "third", "changed-verification"])
def test_complete_from_provider_accepts_terminal_durable_assistant_remount(
    monkeypatch, tmp_path: Path, variant
):
    record = {
        "request-id": "req_remount",
        "state": "failed",
        "revision": 9,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "provider-session-id": "conversation",
            "prompt-message-id": "prompt-1",
            "assistant-message-id": "assistant-before-remount",
            "submission-proven": True,
            "prompt-text-digest": PromptFingerprint.from_text("request").digest,
        },
    }
    snapshot = SimpleNamespace(
        url=record["provider-metadata"]["chat-url"],
        error_present=False,
        latest_assistant_text="captured answer after remount",
        latest_user_text="request",
        latest_user_id="prompt-1",
        latest_assistant_id="assistant-after-remount",
        terminal_witness_assistant_id="assistant-after-remount",
        generating=False,
        dom_signals=frozenset({"completion-control", "response-complete-status"}),
        message_refs=(
            ChatMessageRef(role="user", message_id="prompt-1", text="request", sequence=0),
            ChatMessageRef(
                role="assistant",
                message_id="assistant-before-remount",
                text="partial answer",
                sequence=1,
            ),
            ChatMessageRef(
                role="assistant",
                message_id="assistant-after-remount",
                text="captured answer after remount",
                sequence=2,
            ),
        ),
    )
    snapshot.message_refs = (
            replace(snapshot.message_refs[0], renderer_turn_id="turn"),
            replace(snapshot.message_refs[1], message_id=("assistant-before-remount" if variant == "retained" else "thinking"), renderer_turn_id="turn", renderer_unit_id="unit"),
            replace(snapshot.message_refs[2], renderer_turn_id="turn", renderer_unit_id="unit"),
    )
    if variant == "foreign":
        snapshot.message_refs = (replace(snapshot.message_refs[0], text="foreign"), *snapshot.message_refs[1:])
    if variant == "branch":
        snapshot.message_refs = (*snapshot.message_refs[:2], replace(snapshot.message_refs[2], renderer_unit_id="other"))
    if variant == "third":
        snapshot.message_refs += (replace(snapshot.message_refs[2], message_id="third", sequence=3),)
    snapshots = iter([snapshot, copy.deepcopy(snapshot)])
    if variant == "changed-verification":
        changed = copy.deepcopy(snapshot)
        changed.message_refs = (*changed.message_refs[:2], replace(changed.message_refs[2], renderer_unit_id="other"))
        snapshots = iter([snapshot, changed])
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
            capture_latest_response=lambda *_args, **_kwargs: {
                "outcome": "captured",
                "snapshot": next(snapshots),
            }
        ),
    )
    monkeypatch.setattr(
        api.store,
        "transition_operator_terminal",
        lambda *_args, **_kwargs: {**record, "state": "completed", "revision": 10},
    )

    if variant in {"foreign", "branch", "third", "changed-verification"}:
        with pytest.raises(AudiaGenticError):
            api.complete_execution_from_provider(tmp_path, "req_remount")
        return
    result = api.complete_execution_from_provider(tmp_path, "req_remount")

    assert result["state"] == "completed"


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


def test_complete_from_provider_uses_same_request_session_turn_evidence(
    monkeypatch, tmp_path: Path
):
    request_id = "req_lagged_projection"
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 3,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "provider-session-id": "conversation",
            "unresolved-turn-pending": True,
            "prompt-message-id": "stale-request-user",
            "submission-proven": True,
        },
    }
    checkpoint = {
        "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
        "project-url": "https://chatgpt.com/g/g-p-project/project",
        "provider-session-id": "conversation",
        "unresolved-turn-pending": True,
        "unresolved-turn-id": request_id,
        "prompt-message-id": "provider-user-2",
        "submission-proven": True,
    }
    snapshot = SimpleNamespace(
        latest_assistant_text="captured answer",
        latest_user_text="request",
        latest_user_id="provider-user-2",
        latest_assistant_id="provider-assistant-2",
        terminal_witness_assistant_id="provider-assistant-2",
        generating=False,
        dom_signals=frozenset({"completion-control"}),
    )
    artifact_ref = {
        "artifact-id": "final-response",
        "request-id": request_id,
        "media-type": "text/plain",
        "bytes": 15,
        "sha256": "hash",
    }
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {})
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: checkpoint)
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(
            capture_latest_response=lambda *_args, **_kwargs: {
                "outcome": "captured",
                "snapshot": snapshot,
            }
        ),
    )
    monkeypatch.setattr(
        api.store,
        "transition_operator_terminal",
        lambda *_args, **_kwargs: {
            **record,
            "state": "completed",
            "revision": 4,
            "response-artifact": artifact_ref,
        },
    )

    result = api.complete_execution_from_provider(tmp_path, request_id)

    assert result["state"] == "completed"
    assert result["response-artifact"] == artifact_ref


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


def test_complete_execution_from_provider_rejects_foreign_unresolved_turn(
    monkeypatch, tmp_path: Path
):
    from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import (
        PromptFingerprint,
    )

    record = {
        "request-id": "req_foreign_unresolved",
        "state": "interrupted",
        "revision": 4,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "unresolved-turn-pending": True,
            "prompt-text-digest": PromptFingerprint.from_text("request A").digest,
            "unresolved-baseline-user-count": 1,
            "unresolved-baseline-assistant-count": 1,
        },
    }
    user_ref = SimpleNamespace(role="user", sequence=2, text="request B", correlation_text="request B")
    assistant_ref = SimpleNamespace(role="assistant", sequence=3, text="foreign answer", correlation_text="foreign answer")
    snapshot = SimpleNamespace(
        latest_assistant_text="foreign answer",
        latest_user_text="request B",
        latest_user_id="foreign-user",
        latest_assistant_id="foreign-assistant",
        terminal_witness_assistant_id="foreign-assistant",
        generating=False,
        dom_signals=frozenset({"completion-control"}),
        user_count=2,
        assistant_count=2,
        message_refs=(user_ref, assistant_ref),
        latest_user_ref=lambda: user_ref,
    )
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {"provider": {"metadata": {}}})
    monkeypatch.setattr(
        sessions_store,
        "session_provider_metadata",
        lambda _: {
            "unresolved-turn-pending": True,
            "unresolved-turn-id": "req_other",
            "prompt-message-id": "foreign-user",
            "submission-proven": True,
        },
    )
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(
            capture_latest_response=lambda *_args, **_kwargs: {"outcome": "captured", "snapshot": snapshot}
        ),
    )

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, "req_foreign_unresolved")

    assert getattr(caught.value, "code", None) == "CON-AGW-156"
    assert caught.value.details["failure-reason"] == "foreign-session-turn"


def test_complete_execution_from_provider_uses_normalized_unresolved_prompt_correlation(
    monkeypatch, tmp_path: Path
):
    from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import (
        PromptFingerprint,
    )

    request_id = "req_unresolved_renderer_label"
    correlation_text = "Implement the requested code change.\n\nPreserve the existing API."
    user_ref = SimpleNamespace(
        role="user",
        sequence=0,
        text=correlation_text,
        # ChatGPT may decorate display text with renderer-only labels. The
        # normalized correlation text is the canonical prompt fingerprint.
        correlation_text=correlation_text,
    )
    assistant_ref = SimpleNamespace(
        role="assistant", sequence=1, text="Implemented.", correlation_text="Implemented."
    )
    snapshot = SimpleNamespace(
        latest_assistant_text="Implemented.",
        latest_user_text=f"User said:\n{correlation_text}\nCopy message",
        latest_user_id="fallback-user-0",
        latest_assistant_id="assistant-1",
        terminal_witness_assistant_id="assistant-1",
        generating=False,
        dom_signals=frozenset({"completion-control"}),
        user_count=1,
        assistant_count=1,
        message_refs=(user_ref, assistant_ref),
        latest_user_ref=lambda: user_ref,
    )
    provider_metadata = {
        "project-url": "https://chatgpt.com/g/g-p-project/project",
        "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
        "provider-session-id": "conversation",
        "prompt-message-id": "fallback-user-0",
        "assistant-message-id": "assistant-1",
        "submission-proven": False,
        "unresolved-turn-pending": True,
        "unresolved-turn-id": request_id,
        "prompt-text-digest": PromptFingerprint.from_text(correlation_text).digest,
        "unresolved-baseline-user-count": 0,
        "unresolved-baseline-assistant-count": 0,
    }
    record = {
        "request-id": request_id,
        "state": "interrupted",
        "revision": 4,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": provider_metadata,
    }
    capture_calls = []
    updated = {**record, "state": "completed"}
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(
        sessions_store,
        "read_session_record",
        lambda *_: {"provider": {"metadata": provider_metadata}},
    )
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: provider_metadata)
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")

    def capture(*_args, **_kwargs):
        capture_calls.append(True)
        return {"outcome": "captured", "snapshot": snapshot}

    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(capture_latest_response=capture),
    )
    monkeypatch.setattr(api.store, "transition_operator_terminal", lambda *_args, **_kwargs: updated)

    result = api.complete_execution_from_provider(tmp_path, request_id)

    assert result["state"] == "completed"
    assert len(capture_calls) == 2


def test_complete_execution_from_provider_rejects_stale_turn_metadata_on_queued_request(
    monkeypatch, tmp_path: Path
):
    """A queued request must not capture the previous request's completed turn."""
    request_id = "req_queued_behind_predecessor"
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 3,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "provider-session-id": "conversation",
            "submission-proven": True,
            "unresolved-turn-pending": True,
            "unresolved-turn-id": "req_previous_turn",
            "prompt-message-id": "previous-prompt",
            "assistant-message-id": "previous-assistant",
            "prompt-text-digest": "previous-prompt-digest",
        },
    }
    capture_calls = 0

    def capture(*_args, **_kwargs):
        nonlocal capture_calls
        capture_calls += 1
        return {"outcome": "captured", "snapshot": object()}

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
        lambda: SimpleNamespace(capture_latest_response=capture),
    )

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, request_id, passive=True)

    assert getattr(caught.value, "code", None) == "CON-AGW-156"
    assert caught.value.details["failure-reason"] == "foreign-unresolved-turn"
    assert capture_calls == 0


def test_complete_execution_from_provider_rejects_foreign_session_turn_over_request_claim(
    monkeypatch, tmp_path: Path
):
    """A current-looking request record cannot override a foreign session fence."""
    request_id = "req_current_turn"
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 3,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "provider-session-id": "conversation",
            "submission-proven": True,
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "prompt-message-id": "current-prompt",
            "assistant-before-message-id": "prior-assistant",
            "prompt-text-digest": "current-prompt-digest",
        },
    }
    capture_calls = 0

    def capture(*_args, **_kwargs):
        nonlocal capture_calls
        capture_calls += 1
        return {"outcome": "captured", "snapshot": object()}

    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(
        sessions_store,
        "read_session_record",
        lambda *_: {"provider": {"metadata": {}}},
    )
    monkeypatch.setattr(
        sessions_store,
        "session_provider_metadata",
        lambda _: {
            "submission-proven": True,
            "unresolved-turn-pending": True,
            "unresolved-turn-id": "req_predecessor_turn",
        },
    )
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(capture_latest_response=capture),
    )

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, request_id, passive=True)

    assert getattr(caught.value, "code", None) == "CON-AGW-156"
    assert caught.value.details["failure-reason"] == "foreign-session-turn"
    assert capture_calls == 0


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
        # Current ChatGPT can expose the response-level status live region
        # without the older Copy/Regenerate control.  The gateway must still
        # commit a proven, quiescent response from this witness.
        dom_signals=frozenset({"response-complete-status"}),
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


def test_complete_execution_from_provider_accepts_virtualized_prompt_id(monkeypatch, tmp_path: Path):
    request_id = "req_virtualized_prompt"
    materialized_prompt = "governed instructions\n\nfinish this review"
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 2,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "prompt-template-digest": hashlib.sha256(materialized_prompt.encode()).hexdigest(),
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "provider-session-id": "conversation",
            "prompt-message-id": "virtualized-prompt-for-assistant-1",
            "assistant-message-id": "assistant-1",
            "submission-proven": True,
        },
    }
    prompt_path = gateway_admitted_prompt_path(tmp_path, request_id)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_bytes(materialized_prompt.encode("utf-8"))
    snapshot = SimpleNamespace(
        latest_assistant_text="answer",
        # The user node is virtualized out of the DOM; ownership is carried by
        # the exact assistant witness and the request's durable session bind.
        latest_user_text="virtualized user node",
        latest_user_id="virtualized-prompt-for-assistant-1",
        latest_assistant_id="assistant-1",
        terminal_witness_assistant_id="assistant-1",
        generating=False,
        dom_signals=frozenset({"response-complete-status"}),
        message_refs=(),
    )
    updated = {**record, "state": "completed"}
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {"provider": {"metadata": {}}})
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: {})
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(capture_latest_response=lambda *args, **kwargs: {"outcome": "captured", "snapshot": snapshot}),
    )
    monkeypatch.setattr(api.store, "transition_operator_terminal", lambda *args, **kwargs: updated)

    result = api.complete_execution_from_provider(tmp_path, request_id)

    assert result["state"] == "completed"


def test_complete_execution_from_provider_rejects_foreign_virtualized_assistant(monkeypatch, tmp_path: Path):
    request_id = "req_foreign_virtualized_prompt"
    record = {
        "request-id": request_id,
        "state": "running",
        "revision": 2,
        "session-id": "ses_capture",
        "resolved-provider-id": "gpt-auto",
        "provider-metadata": {
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation",
            "provider-session-id": "conversation",
            "prompt-message-id": "virtualized-prompt-for-older-assistant",
            "assistant-message-id": "assistant-1",
            "submission-proven": True,
        },
    }
    snapshot = SimpleNamespace(
        latest_assistant_text="later answer",
        latest_user_text="virtualized user node",
        latest_user_id="virtualized-prompt-for-older-assistant",
        latest_assistant_id="assistant-1",
        terminal_witness_assistant_id="assistant-1",
        generating=False,
        dom_signals=frozenset({"response-complete-status"}),
        message_refs=(),
    )
    monkeypatch.setattr(api.store, "read_record", lambda *_: record)
    monkeypatch.setattr(sessions_store, "read_session_record", lambda *_: {"provider": {"metadata": {}}})
    monkeypatch.setattr(sessions_store, "session_provider_metadata", lambda _: {})
    monkeypatch.setattr(sessions_store, "session_provider_id", lambda _: "gpt-auto")
    monkeypatch.setattr(
        session_runtime_module,
        "get_session_runtime",
        lambda: SimpleNamespace(capture_latest_response=lambda *args, **kwargs: {"outcome": "captured", "snapshot": snapshot}),
    )

    with pytest.raises(Exception) as caught:
        api.complete_execution_from_provider(tmp_path, request_id)

    assert getattr(caught.value, "code", None) == "CON-AGW-156"


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
        lambda *_, **__: {
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
        updates={
            "error": {"code": "EXT-GPTAUTO-001", "message": "provider observation failed"},
            "diagnostics": {"version": 1, "classification": "unknown", "certainty": "unknown",
                            "phase": "finalization", "side-effect-state": "may-have-started",
                            "failure-code": "EXT-GPTAUTO-001", "resolution-state": "unresolved",
                            "recovery": {"disposition": "reconcile-required", "allowed-actions": ["reconcile"]},
                            "evidence-count": 1, "coalesced-observation-count": 0},
        },
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
    assert completed["diagnostics"]["resolution-state"] == "resolved"
    assert completed["diagnostics"]["recovery"] == {"disposition": "none", "allowed-actions": []}
    assert api._bounded_terminal_error_fields(completed) == {}


def test_operator_capture_rechecks_session_checkpoint_before_terminal_write(tmp_path: Path):
    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    session = sessions_store.build_session_record(
        session_id="ses-capture-checkpoint-race", created_by_request_id=record["request-id"],
        execution_profile_id="gpt-auto", provider_id="gpt-auto",
        provider_metadata={"unresolved-turn-pending": True, "unresolved-turn-id": record["request-id"]},
    )
    sessions_store.write_session_record(tmp_path, session)
    running = store.transition_record(tmp_path, record["request-id"], "running", updates={
        "session-id": session["session-id"], "started-at": "2026-10-20T00:00:00Z",
    })
    # Another session turn can advance without changing this request revision.
    successor = copy.deepcopy(session)
    successor["provider"]["metadata"]["unresolved-turn-id"] = "req_successor"
    with sessions_store._ordered_session_mutation_lock(tmp_path, session["session-id"]):
        sessions_store.write_session_record(tmp_path, successor)
    with pytest.raises(Exception) as caught:
        store.transition_operator_terminal(
            tmp_path, record["request-id"], expected_revision=running["revision"],
            updates={"__final-response-text": "old captured answer"}, session_id=session["session-id"],
            expected_session_provider=session["provider"], clear_unresolved_turn=True,
        )
    assert getattr(caught.value, "code", None) == "CON-AGW-156"
    assert store.read_record(tmp_path, record["request-id"])["state"] == "running"


def _claim_result_at_terminal_boundary(root, request_id, generation, connection):
    from contextlib import contextmanager

    from audiagentic.components.agents.gateway import replay
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    original_lock = replay._lock
    @contextmanager
    def checked_lock(*args, **kwargs):
        probe = original_lock(*args, **kwargs)
        probe._timeout = 0.15
        try:
            with probe:
                connection.send("unexpected-lock-acquisition")
        except AudiaGenticError as exc:
            connection.send(("lock-blocked", exc.code))
        with original_lock(*args, **kwargs):
            yield
    replay._lock = checked_lock
    try:
        connection.send("ready")
        assert connection.recv() == "invalidate-claim"
        result = replay.record_recovery_result(
            Path(root), request_id, action_attempt_id="capture-claim",
            claim_generation=generation, outcome="competing-observation",
        )
        connection.send((result["event"], store.read_record(Path(root), request_id)["state"]))
    finally:
        connection.close()


def test_claim_result_writer_cannot_invalidate_between_final_check_and_write(tmp_path, monkeypatch):
    import importlib
    import multiprocessing

    from audiagentic.components.agents.gateway import replay
    from audiagentic.components.agents.gateway.store import _transitions
    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    running = store.transition_record(tmp_path, record["request-id"], "running")
    claim = replay.prepare_recovery_action(
        tmp_path, record["request-id"], action_attempt_id="capture-claim", action="reconcile",
        action_kind="reconcile", attempt_epoch=1, retry_budget=0, submission_proven=True,
    )
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    worker = importlib.import_module("tests.unit.agents.test_agents_gateway_provider_capture")._claim_result_at_terminal_boundary
    process = context.Process(target=worker, args=(str(tmp_path), record["request-id"], claim["claim-generation"], child))
    original_write = _transitions.write_record
    def write_after_competitor_attempt(*args, **kwargs):
        parent.send("invalidate-claim")
        assert parent.poll(15), "claim writer did not attempt the lock"
        assert parent.recv() == ("lock-blocked", "TO-PROC-002")
        return original_write(*args, **kwargs)
    monkeypatch.setattr(_transitions, "write_record", write_after_competitor_attempt)
    try:
        process.start()
        child.close()
        assert parent.poll(15)
        assert parent.recv() == "ready"
        completed = store.transition_operator_terminal(
            tmp_path, record["request-id"], expected_revision=running["revision"], updates={},
            recovery_attempt_id="capture-claim", recovery_claim_generation=claim["claim-generation"],
        )
        assert completed["state"] == "completed"
        assert parent.poll(15)
        assert parent.recv() == ("action-result", "completed")
        process.join(10)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()


def _capture_waiting_on_session_lock(root, request_id, revision, session, connection):
    """Spawn-safe worker: signal exactly before the real cross-process lock."""
    from contextlib import contextmanager
    original_lock = sessions_store._ordered_session_mutation_lock
    @contextmanager
    def observed_lock(*args, **kwargs):
        connection.send("waiting-for-session-lock")
        with original_lock(*args, **kwargs):
            yield
    sessions_store._ordered_session_mutation_lock = observed_lock
    try:
        store.transition_operator_terminal(
            Path(root), request_id, expected_revision=revision, updates={},
            session_id=session["session-id"], expected_session_provider=session["provider"],
        )
    except Exception as exc:
        connection.send(("rejected", getattr(exc, "code", None)))
    else:
        connection.send(("completed", None))
    finally:
        connection.close()


def test_capture_process_cannot_commit_after_successor_checkpoint_write(tmp_path):
    import importlib
    import multiprocessing
    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    session = sessions_store.build_session_record(
        session_id="ses-cross-process-capture", created_by_request_id=record["request-id"],
        execution_profile_id="gpt-auto", provider_id="gpt-auto",
        provider_metadata={"unresolved-turn-id": record["request-id"], "unresolved-turn-pending": True},
    )
    sessions_store.write_session_record(tmp_path, session)
    running = store.transition_record(tmp_path, record["request-id"], "running")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    worker = importlib.import_module("tests.unit.agents.test_agents_gateway_provider_capture")._capture_waiting_on_session_lock
    process = context.Process(target=worker, args=(
        str(tmp_path), record["request-id"], running["revision"], session, child,
    ))
    try:
        with sessions_store._ordered_session_mutation_lock(tmp_path, session["session-id"]):
            process.start()
            child.close()
            assert parent.poll(15), "capture process did not reach session lock"
            assert parent.recv() == "waiting-for-session-lock"
            successor = copy.deepcopy(session)
            successor["provider"]["metadata"]["unresolved-turn-id"] = "req_successor"
            sessions_store.write_session_record(tmp_path, successor)
        assert parent.poll(15), "capture process did not finish after lock release"
        assert parent.recv() == ("rejected", "CON-AGW-156")
        process.join(10)
        assert process.exitcode == 0
        assert store.read_record(tmp_path, record["request-id"])["state"] == "running"
        current = sessions_store.read_session_record(tmp_path, session["session-id"])
        assert current["provider"]["metadata"]["unresolved-turn-id"] == "req_successor"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()


@pytest.mark.parametrize("delay_site", ["artifact", "session-lock"])
def test_capture_rejects_claim_expiring_before_terminal_write(tmp_path, monkeypatch, delay_site):
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone

    from audiagentic.components.agents.gateway import output, replay

    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    running = store.transition_record(tmp_path, record["request-id"], "running")
    session = sessions_store.build_session_record(
        session_id="ses-lease-expiry", created_by_request_id=record["request-id"],
        execution_profile_id="gpt-auto", provider_id="gpt-auto",
    )
    sessions_store.write_session_record(tmp_path, session)
    claim = replay.prepare_recovery_action(
        tmp_path, record["request-id"], action_attempt_id="capture-expiring",
        action="reconcile", action_kind="reconcile", attempt_epoch=1,
        retry_budget=0, submission_proven=True,
    )
    clock = [datetime.now(timezone.utc)]
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]
    monkeypatch.setattr(replay, "datetime", ClockDateTime)
    def expire():
        clock[0] += timedelta(seconds=replay.RECOVERY_CLAIM_LEASE_SECONDS + 1)
    if delay_site == "artifact":
        persist = output.persist_final_response
        def delayed_persist(*args, **kwargs):
            result = persist(*args, **kwargs)
            expire()
            return result
        monkeypatch.setattr(output, "persist_final_response", delayed_persist)
        session_args = {}
    else:
        session_lock = sessions_store._ordered_session_mutation_lock
        @contextmanager
        def delayed_lock(*args, **kwargs):
            with session_lock(*args, **kwargs):
                expire()
                yield
        monkeypatch.setattr(sessions_store, "_ordered_session_mutation_lock", delayed_lock)
        session_args = {"session_id": session["session-id"], "expected_session_provider": session["provider"]}
    with pytest.raises(replay.RecoveryClaimLostError):
        store.transition_operator_terminal(
            tmp_path, record["request-id"], expected_revision=running["revision"],
            updates={"__final-response-text": "captured answer"},
            recovery_attempt_id="capture-expiring", recovery_claim_generation=claim["claim-generation"],
            **session_args,
        )
    current = store.read_record(tmp_path, record["request-id"])
    assert current["state"] == "running"
    assert current["revision"] == running["revision"]
    assert not current.get("response-artifact")


@pytest.mark.parametrize("clear_conflict", [False, True])
def test_capture_retains_private_checkpoint_until_live_handoff(tmp_path, monkeypatch, clear_conflict):
    request = store.build_record(execution_profile_id="gpt-auto", prompt_body="request", session_id="ses-capture-handoff")
    store.write_record(tmp_path, request)
    checkpoint = {
        "unresolved-turn-id": request["request-id"], "unresolved-turn-pending": True,
        "submission-attempt-id": "original-attempt", "prompt-text-digest": "digest",
        "submission-stage": "send-click-acknowledged", "send-intent-ever": True,
    }
    session = sessions_store.build_session_record(
        session_id=request["session-id"], created_by_request_id=request["request-id"],
        execution_profile_id="gpt-auto", provider_id="gpt-auto", provider_metadata=checkpoint,
    )
    sessions_store.write_session_record(tmp_path, session)
    running = store.transition_record(tmp_path, request["request-id"], "running")
    if clear_conflict:
        clear = sessions_store._clear_terminal_submission_checkpoint_locked
        def conflicting_clear(*args, **kwargs):
            changed = sessions_store.read_session_record(tmp_path, session["session-id"])
            changed["provider"]["metadata"]["submission-attempt-id"] = "successor-attempt"
            sessions_store.write_session_record(tmp_path, changed)
            return clear(*args, **kwargs)
        monkeypatch.setattr(sessions_store, "_clear_terminal_submission_checkpoint_locked", conflicting_clear)
    completed = store.transition_operator_terminal(
        tmp_path, request["request-id"], expected_revision=running["revision"],
        updates={"__final-response-text": "captured answer"}, session_id=session["session-id"],
        expected_session_provider=session["provider"], expected_session_binding=session.get("binding"),
        recovered_binding={"chat-url": "https://chatgpt.com/g/g-p-project/c/conversation", "target-id": "captured-target"},
        clear_unresolved_turn=True,
    )
    marker = completed["terminal-finalization"]
    assert marker["pre-clear-checkpoint"] == checkpoint
    assert "expected-session-binding" in marker
    metadata = sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, session["session-id"]))
    if clear_conflict:
        assert metadata["submission-attempt-id"] == "successor-attempt"
        assert metadata["unresolved-turn-pending"] is True
        assert "chat-url" not in metadata
    else:
        assert metadata["unresolved-turn-pending"] is False
        assert "unresolved-turn-id" not in metadata
        assert metadata["target-id"] == "captured-target"
    # Replay must not discard the only pre-clear identity while live handoff
    # is still pending, including after session cleanup has already succeeded.
    assert store.repair_pending_terminal_finalization(tmp_path, request["request-id"]) is False
    assert store.read_record(tmp_path, request["request-id"])["terminal-finalization"] == marker


def test_unsuccessful_legacy_capture_clear_keeps_replay_marker(tmp_path, monkeypatch):
    request = store.build_record(execution_profile_id="gpt-auto", prompt_body="request", session_id="ses-clear-refused")
    store.write_record(tmp_path, request)
    session = sessions_store.build_session_record(
        session_id=request["session-id"], created_by_request_id=request["request-id"],
        execution_profile_id="gpt-auto", provider_id="gpt-auto",
        provider_metadata={"unresolved-turn-id": request["request-id"], "unresolved-turn-pending": True},
    )
    sessions_store.write_session_record(tmp_path, session)
    running = store.transition_record(tmp_path, request["request-id"], "running")
    monkeypatch.setattr(sessions_store, "_clear_terminal_submission_checkpoint_locked", lambda *args, **kwargs: False)
    completed = store.transition_operator_terminal(
        tmp_path, request["request-id"], expected_revision=running["revision"],
        updates={"__final-response-text": "captured answer"}, session_id=session["session-id"], clear_unresolved_turn=True,
    )
    assert completed.get("terminal-finalization")
    assert store.repair_pending_terminal_finalization(tmp_path, request["request-id"]) is False
    assert store.read_record(tmp_path, request["request-id"]).get("terminal-finalization")


def test_operator_provider_capture_persists_replayable_session_finalization(tmp_path: Path):
    """The capture path's cross-record cleanup marker is schema-valid and replayable."""
    from audiagentic.components.agents.gateway.session import sessions_store

    record = store.build_record(execution_profile_id="gpt-auto", prompt_body="request")
    store.write_record(tmp_path, record)
    session = sessions_store.build_session_record(
        session_id="ses-capture-finalization",
        created_by_request_id=record["request-id"],
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_metadata={"unresolved-turn-pending": True, "unresolved-turn-id": record["request-id"]},
    )
    sessions_store.write_session_record(tmp_path, session)
    running = store.transition_record(
        tmp_path,
        record["request-id"],
        "running",
        updates={"session-id": session["session-id"], "started-at": "2026-09-27T00:00:00Z"},
    )

    completed = store.transition_operator_terminal(
        tmp_path,
        record["request-id"],
        expected_revision=running["revision"],
        updates={"__final-response-text": "captured answer"},
        session_id=session["session-id"],
        clear_unresolved_turn=True,
    )

    assert completed["state"] == "completed"
    assert "terminal-finalization" not in completed
    metadata = sessions_store.session_provider_metadata(
        sessions_store.read_session_record(tmp_path, session["session-id"])
    )
    assert metadata["unresolved-turn-pending"] is False
    assert metadata["recovery-state"] == "terminal-captured"
