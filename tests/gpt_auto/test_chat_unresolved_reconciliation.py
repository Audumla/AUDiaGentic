from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto import session_transport as transport_module
from audiagentic.components.providers.adapters.gpt_auto.cdp.client import CdpError
from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot
from audiagentic.components.providers.adapters.gpt_auto.turn import (
    _terminal_attempt_fingerprint,
    _terminal_checkpoint_fingerprint,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.agent_session import (
    ControlDisposition,
    CorrelationQuality,
    SessionControlAction,
    SessionControlRequest,
    SessionFailureDisposition,
    SessionPrompt,
    TransportObservationKind,
)

from .test_greenfield_config_urls import valid_config


def _chat(*, response_stability_seconds: float = 6.0, unresolved: bool = True) -> PersistentChat:
    config_dict = valid_config()
    config_dict["turn"]["response-stability-seconds"] = response_stability_seconds
    chat = PersistentChat(
        ag_session_id="session-1",
        project_name="project",
        project_url=None,
        runtime=object(),  # unused: test snapshots are injected directly
        config=GptAutoConfig.from_dict(config_dict),
        binding_sink=lambda update: None,
        resume_provider_metadata=(
            {"unresolved-turn-pending": True, "prompt-message-id": "u1"}
            if unresolved else {}
        ),
    )
    chat.page_handle = "page-1"
    return chat


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_external_capture_releases_observer_without_stop_or_checkpoint_clear(monkeypatch, resume):
    chat = _chat(unresolved=True)
    chat.state = ChatState.READY
    chat._checkpoint_metadata.update({"unresolved-turn-id": "req-captured", "submission-attempt-id": "attempt-captured"})
    checkpoint = chat._private_terminal_checkpoint_projection()
    async def ready():
        return None
    chat.ensure_ready = ready
    started = asyncio.Event()
    turns = []
    async def observe(turn):
        turns.append(turn)
        turn.side_effect_attempted = True
        started.set()
        await asyncio.Event().wait()
    if resume:
        monkeypatch.setattr(transport_module.GptAutoTurn, "resume_existing", observe)
    else:
        monkeypatch.setattr(transport_module.GptAutoTurn, "_run", observe)
    def forbidden_cancel(*args, **kwargs):
        raise AssertionError("capture must not request provider Stop")
    monkeypatch.setattr(transport_module.GptAutoTurn, "cancel", forbidden_cancel)
    transport = GptAutoSessionTransport(chat)
    captured = asyncio.Event()
    request = SessionPrompt(turn_id="req-captured", body="original", completion_token=captured)
    method = transport.resume_existing if resume else transport.prompt
    pending = asyncio.create_task(method(request, lambda observation: None))
    await asyncio.wait_for(started.wait(), timeout=1)
    captured.set()
    result = await asyncio.wait_for(pending, timeout=1)
    assert result.stop_reason == "externally-captured"
    assert result.final_summary is None
    assert chat._private_terminal_checkpoint_projection() == checkpoint
    assert transport._active_turn is None
    assert turns[0]._stop_task is None


@pytest.mark.asyncio
async def test_delayed_turn_cleanup_cannot_clear_successor_checkpoint_writer():
    chat = _chat(unresolved=False)
    writes = []
    old_sink = lambda metadata: writes.append(("old", metadata))
    successor_sink = lambda metadata: writes.append(("successor", metadata))
    chat.set_turn_session_checkpoint_sink(old_sink)
    chat.set_turn_session_checkpoint_sink(successor_sink)
    assert chat.clear_turn_session_checkpoint_sink(old_sink) is False
    await chat._persist_checkpoint({"unresolved-turn-id": "req_successor"})
    assert writes == [("successor", {"unresolved-turn-id": "req_successor"})]
    assert chat.clear_turn_session_checkpoint_sink(successor_sink) is True
    assert chat._turn_session_checkpoint_sink is None


@pytest.mark.asyncio
async def test_successor_turn_checkpoint_does_not_invoke_completed_opening_owner(tmp_path):
    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.session import sessions_store
    from audiagentic.components.agents.gateway.session.sessions import (
        _make_submission_checkpoint_sink,
    )

    session_id = "ses-reused-checkpoint"
    project_id = "g-p-project"
    owner = {"dispatch_owner_epoch": "owner", "worker_id": "worker", "attempt_epoch": 1}
    for request_id, state in (("req_opener", "completed"), ("req_successor", "running")):
        request = store.build_record(
            request_id=request_id, execution_profile_id="gpt-auto", prompt_body="request",
            session_id=session_id, resolved_provider_id="gpt-auto",
        )
        request.update({"state": state, "worker-id": "worker", "dispatch-owner-epoch": "owner",
                        "attempt-epoch": 1, "provider-metadata": {"project-id": project_id}})
        store.write_record(tmp_path, request)
    session = sessions_store.build_session_record(
        session_id=session_id, created_by_request_id="req_opener", execution_profile_id="gpt-auto",
        provider_id="gpt-auto", provider_metadata={"project-id": project_id},
    )
    sessions_store.write_session_record(tmp_path, session)
    old_sink = _make_submission_checkpoint_sink(tmp_path, session_id, request_id="req_opener", **owner)
    current_sink = _make_submission_checkpoint_sink(tmp_path, session_id, request_id="req_successor", **owner)
    checkpoint = {
        "unresolved-turn-id": "req_successor", "unresolved-turn-pending": True,
        "submission-state": "prepared", "submission-proven": False,
        "prompt-text-digest": "current-prompt-fingerprint",
        "unresolved-baseline-user-count": 1, "unresolved-baseline-assistant-count": 1,
    }
    # The former opener callback really is invalid now; invoking it was the
    # live regression, even though the durable predecessor had completed.
    with pytest.raises(AudiaGenticError, match="request owner fence"):
        await old_sink(checkpoint)

    chat = _chat(unresolved=False)
    chat.checkpoint_sink = old_sink
    chat.set_turn_session_checkpoint_sink(current_sink)
    audit = []

    def request_sink(metadata):
        durable = sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, session_id))
        assert durable["unresolved-turn-id"] == "req_successor"
        audit.append(metadata)

    chat.set_request_metadata_sink(request_sink)
    await chat._persist_checkpoint(checkpoint)
    assert audit == [checkpoint]
    chat.set_turn_session_checkpoint_sink(None)
    chat.set_request_metadata_sink(None)
    assert chat._turn_session_checkpoint_sink is None


@pytest.mark.parametrize("case", ["valid", "attempt-changed", "prompt-changed", "foreign-turn", "pending", "foreign-chat", "busy"])
@pytest.mark.parametrize("proven", [False, True])
def test_sync_cleared_predecessor_requires_exact_idle_checkpoint(case, proven):
    chat = _chat(unresolved=True)
    chat.state = ChatState.READY
    chat._submission_proven = proven
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation"
    chat._checkpoint_metadata.update({
        "unresolved-turn-id": "req_previous", "submission-attempt-id": "attempt-previous",
        "submission-state": "dispatching", "submission-stage": "send-click-acknowledged",
        "send-intent-ever": True, "prompt-text-digest": "prompt-digest",
        "unresolved-baseline-user-count": 0, "unresolved-baseline-assistant-count": 0,
    })
    expected = chat._private_terminal_checkpoint_projection()
    cleared = {"unresolved-turn-pending": False, "chat-url": chat.chat_url}
    if case == "attempt-changed":
        expected["submission-attempt-id"] = "different-attempt"
    elif case == "prompt-changed":
        expected["prompt-text-digest"] = "different-prompt"
    elif case == "foreign-turn":
        expected["unresolved-turn-id"] = "req_foreign"
    elif case == "pending":
        cleared["unresolved-turn-pending"] = True
    elif case == "foreign-chat":
        cleared["chat-url"] = "https://chatgpt.com/g/g-p-project/c/other"
    elif case == "busy":
        chat.state = ChatState.BUSY
    assert chat.synchronize_cleared_predecessor_checkpoint("req_previous", expected, cleared) is (case == "valid")
    assert chat.unresolved_turn_pending is (case != "valid")
    assert chat._submission_proven is (False if case == "valid" else proven)
    if case == "valid":
        assert chat.synchronize_cleared_predecessor_checkpoint("req_previous", expected, cleared) is True


@pytest.mark.asyncio
async def test_proof_checkpoint_rebuild_preserves_dispatch_identity_for_capture():
    chat = _chat(unresolved=True)
    chat.state = ChatState.READY
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation"
    await chat.persist_unresolved_checkpoint(turn_id="req_previous", baseline=None)
    await chat.mark_submission_dispatching(turn_id="req_previous")
    await chat.persist_submission_stage(turn_id="req_previous", stage="send-intent")
    await chat.persist_submission_stage(turn_id="req_previous", stage="send-click-acknowledged")
    dispatch = chat._private_terminal_checkpoint_projection()
    chat.mark_prompt_submitted("u_current", "a_previous", "current prompt")
    await chat.persist_unresolved_checkpoint(turn_id="req_previous", baseline=None)
    current = chat._private_terminal_checkpoint_projection()
    for key in ("submission-attempt-id", "submission-stage", "send-intent-ever"):
        assert current[key] == dispatch[key]
    cleared = {"unresolved-turn-pending": False, "chat-url": chat.chat_url}
    assert chat.synchronize_cleared_predecessor_checkpoint("req_previous", current, cleared)


@pytest.mark.asyncio
async def test_checkpoint_rebuild_does_not_copy_foreign_attempt_stage():
    chat = _chat(unresolved=True)
    chat._checkpoint_metadata = {
        "unresolved-turn-id": "req_previous", "submission-attempt-id": "old-attempt",
        "submission-stage": "send-click-acknowledged", "send-intent-ever": True,
    }
    await chat.persist_unresolved_checkpoint(turn_id="req_new", baseline=None)
    projection = chat._private_terminal_checkpoint_projection()
    assert projection["unresolved-turn-id"] == "req_new"
    assert not {"submission-attempt-id", "submission-stage", "send-intent-ever"}.intersection(projection)


@pytest.mark.parametrize("case", ["valid", "wrong-attempt", "wrong-prompt", "missing-checkpoint", "artifact-corrupt", "stage-changed", "busy", "foreign-chat"])
def test_manual_capture_residue_uses_terminal_request_checkpoint_for_idle_memory(tmp_path, monkeypatch, case):
    from audiagentic.components.agents.gateway import output
    from audiagentic.components.agents.gateway.session import dispatch, sessions
    chat = _chat(unresolved=True)
    chat.state = ChatState.READY
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation"
    chat._checkpoint_metadata.update({
        "unresolved-turn-id": "req_captured", "submission-attempt-id": "attempt-captured",
        "submission-state": "dispatching", "submission-stage": "send-click-acknowledged",
        "send-intent-ever": True, "prompt-text-digest": "prompt-digest",
    })
    pre_clear = chat._private_terminal_checkpoint_projection()
    artifact = output.persist_final_response(tmp_path, "req_captured", "verified answer", allow_terminal=True)
    predecessor = {
        "request-id": "req_captured", "state": "completed", "session-id": "ses_shared",
        "response-artifact": artifact, "provider-metadata": pre_clear,
    }
    residue = {
        "unresolved-turn-pending": False, "submission-attempt-id": "attempt-captured",
        "submission-stage": "send-click-acknowledged", "send-intent-ever": True,
    }
    cleared = {"unresolved-turn-pending": False, "chat-url": chat.chat_url}
    if case == "wrong-attempt":
        predecessor["provider-metadata"] = {**pre_clear, "submission-attempt-id": "other-attempt"}
    elif case == "wrong-prompt":
        predecessor["provider-metadata"] = {**pre_clear, "prompt-text-digest": "other-prompt"}
    elif case == "missing-checkpoint":
        predecessor["provider-metadata"] = {}
    elif case == "artifact-corrupt":
        predecessor["response-artifact"] = {**artifact, "sha256": "0" * 64}
    elif case == "stage-changed":
        residue["submission-stage"] = "composer-filled"
    elif case == "busy":
        chat.state = ChatState.BUSY
    elif case == "foreign-chat":
        cleared["chat-url"] = "https://chatgpt.com/g/g-p-project/c/other"
    def synchronize(session_id, predecessor_id, *, expected_metadata, persisted_session_metadata):
        assert session_id == "ses_shared"
        return chat.synchronize_cleared_predecessor_checkpoint(predecessor_id, expected_metadata, persisted_session_metadata)
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: SimpleNamespace(synchronize_cleared_predecessor_checkpoint=synchronize))
    assert dispatch._synchronize_cleared_predecessor(tmp_path, "ses_shared", predecessor, residue, cleared) is (case == "valid")
    assert chat.unresolved_turn_pending is (case != "valid")


class _HangingSnapshotBrowser:
    async def page_by_handle(self, _handle: str):
        return SimpleNamespace(target_id="target-1")

    async def snapshot(self, _page, *, signals):
        del signals
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_unresolved_reconciliation_bounds_a_hanging_cdp_snapshot() -> None:
    chat = _chat(unresolved=True)
    chat.config = replace(
        chat.config,
        cdp=replace(chat.config.cdp, protocol_timeout_seconds=0.01),
    )
    chat.runtime = SimpleNamespace(gpt_browser=_HangingSnapshotBrowser())

    result = await asyncio.wait_for(chat._reconcile_unresolved_turn(), timeout=0.2)

    assert result is False
    assert chat._unresolved_recovery_reason == "snapshot-observation-failed"


@pytest.mark.asyncio
async def test_submission_attempt_stages_are_persisted_monotonically_and_send_intent_is_sticky():
    chat = _chat(unresolved=False)
    persisted: list[dict[str, object]] = []
    chat.checkpoint_sink = lambda metadata: persisted.append(dict(metadata))
    chat.set_request_metadata_sink(lambda metadata: persisted.append(dict(metadata)))

    await chat.persist_unresolved_checkpoint(
        turn_id="req-stage",
        baseline=ChatSnapshot(
            url="https://chatgpt.com/g/g-p-project/project",
            composer_present=True,
            composer_editable=True,
            user_count=0,
            assistant_count=0,
            latest_assistant_id=None,
            latest_user_text=None,
            latest_assistant_text=None,
            dom_signals=frozenset(),
            error_present=False,
        ),
    )
    await chat.mark_submission_dispatching(turn_id="req-stage")
    attempt_id = chat._checkpoint_metadata["submission-attempt-id"]

    for stage in ("composer-focused", "composer-filled", "send-intent"):
        assert await chat.persist_submission_stage(turn_id="req-stage", stage=stage) == attempt_id

    assert chat._checkpoint_metadata["submission-stage"] == "send-intent"
    assert chat._checkpoint_metadata["send-intent-ever"] is True
    assert persisted[-1]["submission-attempt-id"] == attempt_id
    assert persisted[-1]["submission-stage"] == "send-intent"

    with pytest.raises(RuntimeError, match="cannot move backwards"):
        await chat.persist_submission_stage(turn_id="req-stage", stage="composer-filled")
    assert chat._checkpoint_metadata["send-intent-ever"] is True


@pytest.mark.asyncio
async def test_proven_checkpoint_preserves_provider_message_proof_source():
    chat = _chat(unresolved=False)
    persisted: list[dict[str, object]] = []
    chat.checkpoint_sink = lambda metadata: persisted.append(dict(metadata))
    chat.set_request_metadata_sink(lambda metadata: persisted.append(dict(metadata)))
    baseline = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/project",
        composer_present=True,
        composer_editable=True,
        user_count=0,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text=None,
        latest_assistant_text=None,
        dom_signals=frozenset(),
        error_present=False,
    )

    await chat.persist_unresolved_checkpoint(turn_id="req-proof", baseline=baseline)
    await chat.mark_submission_dispatching(turn_id="req-proof")
    attempt_id = chat._checkpoint_metadata["submission-attempt-id"]
    chat.mark_prompt_submitted("user-message-1", None, "a test prompt")
    await chat.persist_unresolved_checkpoint(turn_id="req-proof", baseline=baseline)

    assert persisted[-1]["submission-state"] == "proven"
    assert persisted[-1]["submission-attempt-id"] == attempt_id
    assert persisted[-1]["submission-proof-source"] == "provider-user-message"


def test_terminal_finalization_ack_clears_only_the_matching_durable_checkpoint():
    chat = _chat(unresolved=True)
    chat._move(ChatState.RECOVERING)
    chat.unresolved_turn_pending = True
    chat._submission_proven = True
    chat.unresolved_prompt_text_digest = "turn-digest"
    chat._checkpoint_metadata.update(
        {
            "unresolved-turn-id": "req-terminal",
            "submission-state": "proven",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "prompt-text-digest": "turn-digest",
            "unresolved-baseline-user-count": 0,
            "unresolved-baseline-assistant-count": 0,
            "unresolved-baseline-error-alert-occurrences": [],
        }
    )
    terminal_metadata = {
        "unresolved-turn-id": "req-terminal",
        "submission-proven": True,
        "submission-proof-source": "provider-user-message",
        "prompt-text-digest": "turn-digest",
        "unresolved-baseline-user-count": 0,
        "unresolved-baseline-assistant-count": 0,
        "unresolved-baseline-error-alert-occurrences": [],
        "terminal-evidence": {
            "turn-id": "req-terminal",
            "policy": "response-complete",
            "checkpoint-clear-persisted": False,
            "verification-evidence": [
                "not-generating",
                "text-present",
                "completion-control",
            ],
        }
    }
    chat.capture_terminal_checkpoint_metadata("req-terminal")
    # The provider clears its live memory before the gateway terminal write;
    # the private snapshot must survive that handoff.
    chat.clear_unresolved_turn()
    chat._checkpoint_metadata = {}

    assert not chat.acknowledge_terminal_checkpoint_finalization(
        turn_id="req-other",
        terminal_metadata=terminal_metadata,
        persisted_session_metadata={"unresolved-turn-pending": False},
    )
    assert chat.state is ChatState.RECOVERING

    assert chat.acknowledge_terminal_checkpoint_finalization(
        turn_id="req-terminal",
        terminal_metadata=terminal_metadata,
        persisted_session_metadata={"unresolved-turn-pending": False},
    )
    assert not chat.unresolved_turn_pending
    assert chat._checkpoint_metadata == {}
    assert chat.state is ChatState.READY


def test_terminal_checkpoint_metadata_is_private_and_turn_scoped():
    chat = _chat(unresolved=True)
    chat._submission_proven = True
    chat.unresolved_prompt_text_digest = "private-digest"
    chat._checkpoint_metadata.update(
        {
            "unresolved-turn-id": "req-private",
            "submission-state": "proven",
            "submission-attempt-id": "attempt-current",
            "submission-proof-source": "provider-user-message",
            "unresolved-baseline-user-count": 0,
            "unresolved-baseline-assistant-count": 0,
            "unresolved-baseline-error-alert-occurrences": [],
        }
    )

    assert chat.terminal_checkpoint_metadata("req-other") == {}
    chat.capture_terminal_checkpoint_metadata("req-private")
    chat.clear_unresolved_turn()
    chat._checkpoint_metadata = {}
    envelope = chat.terminal_checkpoint_metadata("req-private")
    assert envelope["submission-attempt-id"] == "attempt-current"
    assert envelope["submission-proven"] is True
    assert envelope["submission-proof-source"] == "provider-user-message"
    assert envelope["prompt-text-digest"] == "private-digest"
    envelope["unresolved-baseline-error-alert-occurrences"].append(
        {"digest": "mutated-copy", "ownerPromptMessageId": "id"}
    )
    assert (
        chat._terminal_checkpoint_finalization[
            "unresolved-baseline-error-alert-occurrences"
        ]
        == []
    )


def test_terminal_attempt_fingerprint_links_private_checkpoint_without_exposing_id():
    attempt_id = "attempt-private-opaque-id"
    chat = SimpleNamespace(
        terminal_checkpoint_metadata=lambda turn_id: (
            {
                "unresolved-turn-id": turn_id,
                "submission-attempt-id": attempt_id,
            }
            if turn_id == "req-fingerprint"
            else {}
        )
    )

    fingerprint = _terminal_attempt_fingerprint(chat, "req-fingerprint")

    assert fingerprint is not None
    assert fingerprint != attempt_id
    assert fingerprint == hashlib.sha256(attempt_id.encode()).hexdigest()
    assert _terminal_attempt_fingerprint(chat, "req-other") is None


def test_terminal_checkpoint_fingerprint_binds_turn_and_frozen_prompt_baseline():
    checkpoint = {
        "unresolved-turn-id": "req-checkpoint-fingerprint",
        "submission-attempt-id": "attempt-private-opaque-id",
        "submission-proven": True,
        "prompt-text-digest": "prompt-digest",
        "prompt-message-id": "user-private-id",
        "unresolved-baseline-user-count": 2,
        "unresolved-baseline-assistant-count": 2,
        "unresolved-baseline-error-alert-occurrences": [],
    }
    chat = SimpleNamespace(
        terminal_checkpoint_metadata=lambda turn_id: (
            checkpoint if turn_id == "req-checkpoint-fingerprint" else {}
        )
    )

    fingerprint = _terminal_checkpoint_fingerprint(
        chat, "req-checkpoint-fingerprint"
    )

    assert fingerprint is not None
    assert "attempt-private-opaque-id" not in fingerprint
    assert "user-private-id" not in fingerprint
    assert _terminal_checkpoint_fingerprint(chat, "req-other") is None
    checkpoint["prompt-text-digest"] = "different-prompt-digest"
    assert (
        _terminal_checkpoint_fingerprint(chat, "req-checkpoint-fingerprint")
        != fingerprint
    )


def test_terminal_finalization_ack_rejects_frozen_identity_mismatch():
    chat = _chat(unresolved=True)
    chat._checkpoint_metadata.update(
        {
            "unresolved-turn-id": "req-terminal",
            "submission-state": "proven",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "prompt-text-digest": "original-digest",
        }
    )
    terminal_metadata = {
        "unresolved-turn-id": "req-terminal",
        "submission-proven": True,
        "submission-proof-source": "provider-user-message",
        "prompt-text-digest": "different-digest",
        "terminal-evidence": {
            "turn-id": "req-terminal",
            "policy": "response-complete",
            "verification-evidence": [
                "not-generating",
                "text-present",
                "completion-control",
            ],
        },
    }

    assert not chat.acknowledge_terminal_checkpoint_finalization(
        turn_id="req-terminal",
        terminal_metadata=terminal_metadata,
        persisted_session_metadata={"unresolved-turn-pending": False},
    )
    assert chat.unresolved_turn_pending is True


@pytest.mark.asyncio
async def test_submission_stage_checkpoint_failure_is_fail_closed_before_send_intent():
    chat = _chat(unresolved=False)
    await chat.persist_unresolved_checkpoint(
        turn_id="req-stage-failure",
        baseline=ChatSnapshot(
            url="https://chatgpt.com/g/g-p-project/project",
            composer_present=True,
            composer_editable=True,
            user_count=0,
            assistant_count=0,
            latest_assistant_id=None,
            latest_user_text=None,
            latest_assistant_text=None,
            dom_signals=frozenset(),
            error_present=False,
        ),
    )
    await chat.mark_submission_dispatching(turn_id="req-stage-failure")

    async def fail_checkpoint(_metadata):
        raise OSError("durable checkpoint unavailable")

    chat.set_request_metadata_sink(fail_checkpoint)
    with pytest.raises(OSError, match="checkpoint unavailable"):
        await chat.persist_submission_stage(
            turn_id="req-stage-failure", stage="send-intent"
        )

    assert chat._checkpoint_metadata["submission-stage"] == "dispatching"
    assert chat._checkpoint_metadata["send-intent-ever"] is False


@pytest.mark.asyncio
async def test_readiness_failure_is_typed_as_not_started_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = _chat(unresolved=False)
    transport = GptAutoSessionTransport(chat)
    retained_errors: list[AudiaGenticError] = []

    async def fail_ready() -> None:
        raise RuntimeError("private readiness detail")

    async def retain(error: AudiaGenticError) -> bool:
        retained_errors.append(error)
        return True

    chat.ensure_ready = fail_ready  # type: ignore[method-assign]
    chat.retain_after_turn_failure = retain  # type: ignore[method-assign]

    with pytest.raises(AudiaGenticError) as raised:
        await transport.prompt(
            SessionPrompt(turn_id="req-1", body="hello"),
            lambda _observation: None,
        )

    error = raised.value
    assert error.code == "EXT-GPTAUTO-004"
    assert error.details["failure-stage"] == "readiness"
    assert error.details["submission-state"] == "not_started"
    assert error.details["retryable-same-session"] is True
    assert error.__cause__ is not None
    assert retained_errors[0].details["retryable-same-session"] is False
    assert transport.turn_failure_disposition() is SessionFailureDisposition.RETAIN


@pytest.mark.asyncio
async def test_missing_idle_renderer_retains_durable_chat_for_queued_readiness_retry():
    chat = _chat(unresolved=False)
    chat.state = ChatState.RECOVERING
    chat.page_handle = None
    chat.provider_session_id = "conversation-1"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation-1"

    async def still_recovering():
        raise RuntimeError("gpt-auto chat is not ready (state=recovering)")

    chat.ensure_ready = still_recovering
    transport = GptAutoSessionTransport(chat)
    with pytest.raises(AudiaGenticError) as raised:
        await transport.prompt(SessionPrompt(turn_id="req-next", body="new request"), lambda _item: None)

    assert chat.state is ChatState.RECOVERING  # retained, never falsely READY
    assert transport.turn_failure_disposition() is SessionFailureDisposition.RETAIN
    assert raised.value.details["retryable-same-session"] is True
    assert raised.value.details["submission-attempted"] is False
    assert transport._active_turn is None  # no composer/Send path was reached


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["active", "unresolved", "unknown-proof", "wrong-ref", "owner-expired", "binding-error", "auth"])
async def test_readiness_retention_requires_unsent_matching_conversation_and_live_owner(blocked):
    chat = _chat(unresolved=False)
    chat.state = ChatState.RECOVERING
    chat.page_handle = None
    chat.provider_session_id = "conversation-1"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation-1"
    details = {
        "failure-stage": "readiness", "submission-state": "not_started",
        "submission-attempted": False, "submission-proven": False,
        "submission-ambiguous": False, "previous-turn-unresolved": False,
    }
    if blocked == "active":
        chat.active_turn_id = "req-old"
    elif blocked == "unresolved":
        chat.unresolved_turn_pending = True
    elif blocked == "unknown-proof":
        details.pop("submission-attempted")
    elif blocked == "wrong-ref":
        chat.chat_url += "-other"
    elif blocked == "owner-expired":
        chat.set_page_mutation_owner_probe(lambda: False)
    elif blocked == "binding-error":
        details["cause-type"] = "ProviderBindingIntegrityError"
    elif blocked == "auth":
        chat._last_snapshot = _terminal_snapshot(dom_signals=frozenset({"auth-required"}))
    assert not await chat.retain_after_turn_failure(AudiaGenticError(
        code="EXT-GPTAUTO-004", kind="providers", message="readiness lost", details=details,
    ))


@pytest.mark.asyncio
async def test_load_error_readiness_preserves_safe_fresh_session_recovery_evidence() -> None:
    chat = _chat(unresolved=False)
    transport = GptAutoSessionTransport(chat)
    typed = AudiaGenticError(
        code="EXT-GPTAUTO-005",
        kind="providers",
        message="conversation could not be loaded after bounded recovery",
        details={
            "failure-reason": "conversation-load-failed",
            "submission-proven": False,
            "submission-attempted": False,
            "submission-ambiguous": False,
            "dom-signals": ["conversation-load-failed"],
        },
    )

    async def fail_ready() -> None:
        raise typed

    chat.ensure_ready = fail_ready  # type: ignore[method-assign]
    chat.retain_after_turn_failure = lambda _error: asyncio.sleep(0, result=False)  # type: ignore[method-assign]

    with pytest.raises(AudiaGenticError) as raised:
        await transport.prompt(
            SessionPrompt(turn_id="req-load-error", body="hello"),
            lambda _observation: None,
        )

    assert raised.value.code == "EXT-GPTAUTO-005"
    assert raised.value.details["failure-reason"] == "conversation-load-failed"
    assert raised.value.details["submission-proven"] is False
    assert raised.value.details["submission-attempted"] is False
    assert raised.value.details["submission-ambiguous"] is False
    assert raised.value.details["failure-stage"] == "readiness"
    assert raised.value.details["submission-state"] == "not_started"
    assert transport.turn_failure_disposition() is SessionFailureDisposition.TERMINATE


@pytest.mark.asyncio
async def test_prompt_relays_provider_activity_before_slow_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow CDP admission path must not leave the request at activity zero."""
    chat = _chat(unresolved=False)
    transport = GptAutoSessionTransport(chat)
    events: list[tuple[str, object]] = []

    async def ensure_ready() -> None:
        events.append(("ensure-ready", None))

    async def fake_run(_turn) -> object:
        events.append(("turn-run", None))
        return "complete"

    async def sink(observation) -> None:
        events.append(("observation", observation))

    chat.ensure_ready = ensure_ready  # type: ignore[method-assign]
    monkeypatch.setattr(transport_module.GptAutoTurn, "run", fake_run)

    result = await transport.prompt(SessionPrompt(turn_id="req-activity", body="hello"), sink)

    assert result == "complete"
    assert [kind for kind, _ in events] == [
        "observation",
        "ensure-ready",
        "observation",
        "turn-run",
    ]
    observations = [value for kind, value in events if kind == "observation"]
    assert [item.kind for item in observations] == [
        TransportObservationKind.ACTIVITY,
        TransportObservationKind.ACTIVITY,
    ]
    assert [item.attributes["model_activity"] for item in observations] == [
        "preflight-inspected",
        "preflight-evaluated",
    ]
    assert chat._validated_activity_generation == 0


@pytest.mark.asyncio
async def test_physical_tab_clock_ignores_synthetic_connection_heartbeat() -> None:
    chat = _chat(unresolved=False)
    chat._last_validated_activity_monotonic = 100.0
    turn = transport_module.GptAutoTurn(
        chat,
        SessionPrompt(turn_id="req-clock", body="hello"),
        lambda _observation: None,
    )

    await turn._emit(
        TransportObservationKind.ACTIVITY,
        {"model_activity": "connection-refreshing"},
    )
    assert chat._last_validated_activity_monotonic == 100.0
    assert chat._validated_activity_generation == 0

    await turn._emit(
        TransportObservationKind.ACTIVITY,
        {"model_activity": "response-progress"},
    )
    assert chat._last_validated_activity_monotonic > 100.0
    assert chat._validated_activity_generation == 1

    await turn._emit(
        TransportObservationKind.ACTIVITY,
        {"model_activity": "recovery-observing"},
    )
    assert chat._validated_activity_generation == 1


@pytest.mark.asyncio
async def test_unresolved_prior_turn_blocks_presubmit_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = _chat(unresolved=True)
    transport = GptAutoSessionTransport(chat)

    async def fail_ready() -> None:
        raise RuntimeError("not ready")

    chat.ensure_ready = fail_ready  # type: ignore[method-assign]
    chat.retain_after_turn_failure = lambda _error: asyncio.sleep(0, result=True)  # type: ignore[method-assign]

    with pytest.raises(AudiaGenticError) as raised:
        await transport.prompt(
            SessionPrompt(turn_id="req-2", body="hello"),
            lambda _observation: None,
        )

    assert raised.value.details["submission-state"] == "not_started"
    assert raised.value.details["previous-turn-unresolved"] is True
    assert raised.value.details["submission-attempted"] is False
    assert raised.value.details["retryable-same-session"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata,after_metadata", [
    ({}, {}), ({"unresolved-turn-pending": "false"}, {}), (None, {}),
    ({"unresolved-turn-pending": False}, {}), ({}, {"unresolved-turn-pending": False}),
])
async def test_missing_predecessor_evidence_is_not_negative_send_proof(metadata, after_metadata) -> None:
    from audiagentic.components.agents.gateway.diagnostics import classify_error

    chat = _chat(unresolved=False)
    chat.state = ChatState.READY
    checkpoints = iter((metadata, after_metadata))
    chat.unresolved_metadata = lambda: next(checkpoints)  # type: ignore[method-assign]
    transport = GptAutoSessionTransport(chat)

    async def fail_ready() -> None:
        raise RuntimeError("not ready")

    chat.ensure_ready = fail_ready  # type: ignore[method-assign]
    chat.retain_after_turn_failure = lambda _error: asyncio.sleep(0, result=True)  # type: ignore[method-assign]
    with pytest.raises(AudiaGenticError) as raised:
        await transport.prompt(SessionPrompt(turn_id="req-unknown", body="hello"), lambda _observation: None)
    assert raised.value.details["previous-turn-unresolved"] is None
    assert raised.value.details["retryable-same-session"] is False
    assert classify_error(raised.value)["classification"] == "ambiguous-side-effect"


@pytest.mark.asyncio
async def test_failed_session_does_not_retain_request_after_readiness_failure() -> None:
    chat = _chat(unresolved=True)
    chat.state = ChatState.FAILED
    transport = GptAutoSessionTransport(chat)

    async def fail_ready() -> None:
        raise RuntimeError("session is no longer usable")

    chat.ensure_ready = fail_ready  # type: ignore[method-assign]
    chat.retain_after_turn_failure = lambda _error: asyncio.sleep(0, result=True)  # type: ignore[method-assign]

    with pytest.raises(AudiaGenticError) as raised:
        await transport.prompt(
            SessionPrompt(turn_id="req-failed-session", body="hello"),
            lambda _observation: None,
        )

    assert raised.value.details["retryable-same-session"] is False
    assert raised.value.details["chat-state"] == "failed"
    assert transport.turn_failure_disposition() is SessionFailureDisposition.TERMINATE


def _terminal_snapshot(*, dom_signals: frozenset[str]) -> ChatSnapshot:
    return ChatSnapshot(
        url="https://chatgpt.com/c/abc",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=1,
        latest_assistant_id="a1",
        latest_user_text="hi",
        latest_assistant_text="response text",
        dom_signals=dom_signals,
        error_present=False,
        generating=False,
        latest_user_id="u1",
        user_message_ids=("u1",),
        user_message_texts=("hi",),
    )


def test_recovery_transport_rejects_foreign_unresolved_request() -> None:
    chat = _chat()
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-original"
    transport = GptAutoSessionTransport(chat)
    request = SimpleNamespace(turn_id="req-foreign")

    with pytest.raises(RuntimeError, match="does not belong to the recovered request"):
        asyncio.run(transport.resume_existing(request, lambda _observation: None))


@pytest.mark.asyncio
async def test_cancel_during_gateway_gap_is_latched_until_rehydrated_turn_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = _chat()
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-1"
    transport = GptAutoSessionTransport(chat)
    cancel = SessionControlRequest(
        ag_session_id=chat.ag_session_id,
        turn_id="req-1",
        action=SessionControlAction.CANCEL_TURN,
    )

    result = await transport.control(cancel)

    assert result.disposition is ControlDisposition.ACCEPTED
    assert result.correlation_quality is CorrelationQuality.REQUEST_SCOPED

    class _ResumedTurn:
        def __init__(self, *_args) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

        async def resume_existing(self):
            assert self.cancelled is True
            return SimpleNamespace(stop_reason="cancelled")

    monkeypatch.setattr(transport_module, "GptAutoTurn", _ResumedTurn)
    result = await transport.resume_existing(
        SessionPrompt(turn_id="req-1", body="already submitted"),
        lambda _observation: None,
    )

    assert result.stop_reason == "cancelled"


@pytest.mark.asyncio
async def test_pending_recovery_cancel_returns_cancelled_without_resubmission():
    """A cancel latched before resume_existing must remain a real cancellation."""
    chat = _chat()
    chat.state = ChatState.READY
    chat._checkpoint_metadata.update(
        {
            "unresolved-turn-id": "req-1",
            "prompt-message-id": "u1",
            "assistant-message-id": None,
        }
    )
    stop_calls: list[str] = []

    class Bridge:
        async def call(self, method, _params, **_kwargs):
            if method == "submit_prompt":
                raise AssertionError("recovered cancellation must never submit")
            if method == "stop_generation":
                stop_calls.append(method)
                return {"stopped": True}
            return {"ok": True}

    chat.runtime = SimpleNamespace(bridge=Bridge())
    chat.ensure_ready = lambda: asyncio.sleep(0)  # type: ignore[method-assign]
    chat.snapshot = lambda **_kwargs: asyncio.sleep(  # type: ignore[method-assign]
        0, result=_terminal_snapshot(dom_signals=frozenset())
    )
    chat.wait_quiescent = lambda **_kwargs: asyncio.sleep(  # type: ignore[method-assign]
        0, result=_terminal_snapshot(dom_signals=frozenset())
    )
    chat.persist_unresolved_clear = lambda: asyncio.sleep(0)  # type: ignore[method-assign]

    transport = GptAutoSessionTransport(chat)
    cancel = SessionControlRequest(
        ag_session_id=chat.ag_session_id,
        turn_id="req-1",
        action=SessionControlAction.CANCEL_TURN,
    )
    accepted = await transport.control(cancel)
    assert accepted.disposition is ControlDisposition.ACCEPTED

    result = await transport.resume_existing(
        SessionPrompt(turn_id="req-1", body="already submitted"),
        lambda _observation: None,
    )

    assert result.stop_reason == "cancelled"
    assert stop_calls == ["stop_generation"]


@pytest.mark.asyncio
async def test_resume_existing_exposes_definitive_provider_failure_as_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = _chat()
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-1"

    async def retain_and_clear(_error) -> bool:
        chat.clear_unresolved_turn()
        return True

    chat.retain_after_turn_failure = retain_and_clear  # type: ignore[method-assign]

    class _FailedTurn:
        def __init__(self, *_args) -> None:
            pass

        async def resume_existing(self):
            raise AudiaGenticError(
                "EXT-GPTAUTO-003",
                "providers",
                "provider failure policy matched",
                {
                    "failure-reason": "provider-failure-policy-matched",
                    "phase": "response-observation",
                    "evidence": ["error-page"],
                },
            )

    monkeypatch.setattr(transport_module, "GptAutoTurn", _FailedTurn)
    transport = GptAutoSessionTransport(chat)

    with pytest.raises(AudiaGenticError, match="provider failure policy matched"):
        await transport.resume_existing(
            SessionPrompt(turn_id="req-1", body="already submitted"),
            lambda _observation: None,
        )

    assert transport.turn_failure_disposition() is SessionFailureDisposition.TERMINAL_FAILED


@pytest.mark.asyncio
async def test_resume_existing_load_failure_is_terminal_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeated conversation-load outage must fail and close the session path."""
    chat = _chat()
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-1"

    class _FailedTurn:
        def __init__(self, *_args) -> None:
            pass

        async def resume_existing(self):
            raise AudiaGenticError(
                "EXT-GPTAUTO-005",
                "providers",
                "gpt-auto could not load the durable ChatGPT conversation",
                {
                    "failure-reason": "conversation-load-failed",
                    "recovery-reason": "conversation-load-recovery-exhausted",
                    "submission-ambiguous": True,
                },
            )

    monkeypatch.setattr(transport_module, "GptAutoTurn", _FailedTurn)
    transport = GptAutoSessionTransport(chat)

    with pytest.raises(AudiaGenticError, match="could not load"):
        await transport.resume_existing(
            SessionPrompt(turn_id="req-1", body="already submitted"),
            lambda _observation: None,
        )

    assert transport.turn_failure_disposition() is SessionFailureDisposition.TERMINAL_FAILED


@pytest.mark.asyncio
async def test_resume_existing_keeps_durable_session_after_cdp_observation_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed CDP observation error must not fail the session."""
    chat = _chat()
    chat.provider_session_id = "provider-session-1"
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-1"

    async def not_retained_by_legacy_classifier(_error) -> bool:
        # The typed CDP boundary proves the observation channel was lost;
        # it does not prove that the provider turn stopped.
        return False

    chat.retain_after_turn_failure = not_retained_by_legacy_classifier  # type: ignore[method-assign]

    class _InterruptedTurn:
        def __init__(self, *_args) -> None:
            pass

        async def resume_existing(self):
            raise CdpError("CDP connection closed while observing")

    monkeypatch.setattr(transport_module, "GptAutoTurn", _InterruptedTurn)
    transport = GptAutoSessionTransport(chat)

    with pytest.raises(CdpError, match="CDP connection closed"):
        await transport.resume_existing(
            SessionPrompt(turn_id="req-1", body="already submitted"),
            lambda _observation: None,
        )

    assert transport.turn_failure_disposition() is SessionFailureDisposition.RETAIN
    assert chat.state not in {ChatState.FAILED, ChatState.CLOSED}


@pytest.mark.asyncio
async def test_resume_existing_fails_closed_on_unclassified_observation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A generic implementation error must not become durable recovery."""
    chat = _chat()
    chat.provider_session_id = "provider-session-1"
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-1"

    async def not_retained_by_legacy_classifier(_error) -> bool:
        return False

    chat.retain_after_turn_failure = not_retained_by_legacy_classifier  # type: ignore[method-assign]

    class _BrokenTurn:
        def __init__(self, *_args) -> None:
            pass

        async def resume_existing(self):
            raise RuntimeError("unexpected implementation fault")

    monkeypatch.setattr(transport_module, "GptAutoTurn", _BrokenTurn)
    transport = GptAutoSessionTransport(chat)

    with pytest.raises(RuntimeError, match="unexpected implementation fault"):
        await transport.resume_existing(
            SessionPrompt(turn_id="req-1", body="already submitted"),
            lambda _observation: None,
        )

    assert transport.turn_failure_disposition() is SessionFailureDisposition.TERMINATE


@pytest.mark.asyncio
async def test_retain_releases_fence_after_stable_request_owned_provider_error() -> None:
    """A confirmed provider rejection must not poison a healthy chat."""
    chat = _chat(response_stability_seconds=0.001)
    chat.state = ChatState.FAILED
    error_snapshot = ChatSnapshot(
        url="https://chatgpt.com/c/abc",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=1,
        latest_assistant_id="a1",
        latest_user_text="hi",
        latest_assistant_text="older response",
        dom_signals=frozenset({"error-page"}),
        error_present=True,
        generating=False,
        latest_user_id="u1",
        user_message_ids=("u1",),
        user_message_texts=("hi",),
    )
    snapshots = iter([error_snapshot, error_snapshot])
    persisted: list[dict[str, object]] = []
    chat.checkpoint_sink = persisted.append

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return next(snapshots)

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat._binding_token_is_current = (  # type: ignore[method-assign]
        lambda _token: asyncio.sleep(0, result=True)
    )
    retained = await chat.retain_after_turn_failure(
        AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="provider failure policy matched",
            details={
                "failure-reason": "provider-failure-policy-matched",
                "phase": "response-observation",
                "evidence": ["error-page"],
            },
        )
    )

    assert retained is True
    assert chat.state.value == "ready"
    assert chat.unresolved_turn_pending is False
    assert persisted == [{"unresolved-turn-pending": False, "submission-state": "cleared"}]


@pytest.mark.asyncio
async def test_retain_releases_fence_for_correlated_request_error_alert() -> None:
    chat = _chat(response_stability_seconds=0.001)
    chat.state = ChatState.FAILED
    error_snapshot = ChatSnapshot(
        url="https://chatgpt.com/c/abc",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text="hi",
        latest_assistant_text=None,
        dom_signals=frozenset({"error-alert"}),
        error_present=False,
        generating=False,
        latest_user_id="u1",
        user_message_ids=("u1",),
        user_message_texts=("hi",),
    )
    clean_snapshot = replace(error_snapshot, dom_signals=frozenset())
    snapshots = iter([error_snapshot, clean_snapshot])
    chat.snapshot = lambda **_kwargs: asyncio.sleep(0, result=next(snapshots))  # type: ignore[method-assign]
    chat._binding_token_is_current = lambda _token: asyncio.sleep(0, result=True)  # type: ignore[method-assign]
    persisted: list[dict[str, object]] = []
    chat.checkpoint_sink = persisted.append

    retained = await chat.retain_after_turn_failure(
        AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="provider failure policy matched",
            details={
                "failure-reason": "provider-failure-policy-matched",
                "phase": "response-observation",
                "evidence": ["request-error-alert"],
            },
        )
    )
    assert retained is True
    assert chat.unresolved_turn_pending is False
    assert persisted == [{"unresolved-turn-pending": False, "submission-state": "cleared"}]


@pytest.mark.asyncio
async def test_retain_keeps_fence_for_ambiguous_provider_error() -> None:
    chat = _chat(response_stability_seconds=0.001)
    chat.state = ChatState.FAILED
    retained = await chat.retain_after_turn_failure(
        AudiaGenticError(
            code="EXT-GPTAUTO-004",
            kind="providers",
            message="response correlation was ambiguous",
            details={"failure-reason": "unresolved-turn-not-reconciled"},
        )
    )
    assert retained is True
    assert chat.unresolved_turn_pending is True


@pytest.mark.asyncio
async def test_reconcile_retries_delivery_timeout_without_resubmitting() -> None:
    chat = _chat(response_stability_seconds=0.001)
    retry_page = _terminal_snapshot(
        dom_signals=frozenset({"delivery-timeout-retry", "error-alert"})
    )
    terminal = _terminal_snapshot(
        dom_signals=frozenset({"completion-control", "more-actions-menu"})
    )
    snapshots = iter([retry_page, terminal, terminal])
    calls = 0

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return next(snapshots)

    async def fake_retry() -> bool:
        nonlocal calls
        calls += 1
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.retry_delivery_timeout = fake_retry  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True
    assert calls == 1


@pytest.mark.asyncio
async def test_reconcile_does_not_retry_foreign_turn_delivery_control() -> None:
    chat = _chat(response_stability_seconds=0.001)
    foreign = _terminal_snapshot(
        dom_signals=frozenset({"delivery-timeout-retry", "error-alert"})
    )
    foreign = replace(
        foreign,
        latest_user_id="u2",
        latest_user_text="later turn",
        user_message_ids=("u1", "u2"),
        user_message_texts=("hi", "later turn"),
    )
    calls = 0

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return foreign

    async def fake_retry() -> bool:
        nonlocal calls
        calls += 1
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.retry_delivery_timeout = fake_retry  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    assert calls == 0
    assert chat._unresolved_recovery_reason == "delivery-timeout-retry-not-request-owned"


@pytest.mark.asyncio
async def test_reconcile_does_not_retry_completed_turn_with_stale_error() -> None:
    chat = _chat(response_stability_seconds=0.001)
    complete_stale = _terminal_snapshot(
        dom_signals=frozenset(
            {
                "completion-control",
                "more-actions-menu",
                "delivery-timeout-retry",
                "error-alert",
            }
        )
    )
    snapshots = iter([complete_stale, complete_stale, complete_stale])
    calls = 0

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return next(snapshots)

    async def fake_retry() -> bool:
        nonlocal calls
        calls += 1
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.retry_delivery_timeout = fake_retry  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True
    assert calls == 0


@pytest.mark.asyncio
async def test_reconcile_authentication_vetoes_delivery_retry() -> None:
    chat = _chat(response_stability_seconds=0.001)
    blocked = _terminal_snapshot(
        dom_signals=frozenset(
            {"completion-control", "more-actions-menu", "delivery-timeout-retry", "auth-required"}
        )
    )
    calls = 0

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return blocked

    async def fake_retry() -> bool:
        nonlocal calls
        calls += 1
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.retry_delivery_timeout = fake_retry  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    assert calls == 0
    assert chat._unresolved_recovery_reason == "authentication-required"


@pytest.mark.asyncio
async def test_reconcile_accepts_retried_assistant_id_for_exact_prompt() -> None:
    chat = _chat(response_stability_seconds=0.001)
    chat.unresolved_assistant_message_id = "a-old"
    chat.unresolved_assistant_before_id = "a-before"
    chat._checkpoint_metadata["unresolved-baseline-user-count"] = 1
    snapshot = _terminal_snapshot(
        dom_signals=frozenset({"completion-control", "more-actions-menu"})
    )
    snapshots = iter([snapshot, snapshot, snapshot])

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return next(snapshots)

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True


@pytest.mark.asyncio
async def test_reconcile_requires_response_stability_seconds_between_matching_observations():
    """GP38: a single matching fingerprint must not clear the unresolved
    marker immediately -- the same response_stability_seconds gap the main
    completion path enforces is required here too."""
    chat = _chat(response_stability_seconds=6.0)
    snapshot = _terminal_snapshot(dom_signals=frozenset({"completion-control", "more-actions-menu"}))

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return snapshot

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    assert chat.unresolved_turn_pending is True
    assert await chat._reconcile_unresolved_turn() is False, (
        "second observation immediately afterwards must still be blocked by "
        "response_stability_seconds, not just require two matching fingerprints"
    )


@pytest.mark.asyncio
async def test_reconcile_resets_stability_timer_when_terminal_evidence_disappears():
    """GP38/GP40 code review (2026-08-17): a candidate armed by one terminal
    observation must not survive an intervening non-terminal observation.
    Without resetting the timer, "terminal, then briefly not-terminal, then
    terminal again 6s later" would satisfy the elapsed-time check even
    though the candidate was never continuously eligible -- which is
    exactly the flicker scenario observed live."""
    chat = _chat(response_stability_seconds=6.0)
    terminal = _terminal_snapshot(dom_signals=frozenset({"completion-control", "more-actions-menu"}))
    non_terminal = _terminal_snapshot(dom_signals=frozenset())

    sequence = iter([terminal, non_terminal, terminal])

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return next(sequence)

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    assert chat._unresolved_match_fingerprint_at is not None

    assert await chat._reconcile_unresolved_turn() is False
    assert chat._unresolved_match_fingerprint_at is None, (
        "losing terminal completion evidence must discard the in-progress "
        "candidate timer, not let it survive to be revived later"
    )

    assert await chat._reconcile_unresolved_turn() is False, (
        "the third observation re-arms a FRESH candidate -- it must not "
        "immediately clear using a timestamp from before the reset"
    )
    assert chat._unresolved_match_fingerprint_at is not None


@pytest.mark.asyncio
async def test_reconcile_treats_empty_any_of_groups_as_no_completion_requirement():
    """GP38 code review: EvidencePolicy.evaluate() treats an absent/empty
    any-of-groups section as no any-of requirement at all. any(...) over an
    empty sequence is False, so a naive port of that check would make
    unresolved-turn recovery permanently impossible if a future overlay
    legally removed any-of-groups from response-complete."""
    chat = _chat(response_stability_seconds=0.001)
    policy = chat.config.workflow.policy("response-complete")
    object.__setattr__(policy, "any_of_groups", ())
    snapshot = _terminal_snapshot(dom_signals=frozenset())

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return snapshot

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]

    await chat._reconcile_unresolved_turn()
    await asyncio.sleep(1.0)
    result = await chat._reconcile_unresolved_turn()
    assert result is True, chat._unresolved_recovery_diagnostics()


@pytest.mark.asyncio
async def test_reconcile_refreshes_stale_cdp_page_once_before_failure():
    from itertools import chain, repeat
    chat = _chat(response_stability_seconds=0.001)
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/abc"
    chat.provider_session_id = "abc"
    stale = ChatSnapshot(
        url=chat.chat_url,
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text="hi",
        latest_assistant_text=None,
        dom_signals=frozenset({"completion-control", "more-actions-menu"}),
        error_present=False,
        generating=False,
        latest_user_id="u1",
        user_message_ids=("u1",),
        user_message_texts=("hi",),
    )
    terminal = _terminal_snapshot(dom_signals=frozenset({"completion-control", "more-actions-menu"}))
    # A terminal provider page remains terminal across stability/identity
    # rechecks. Do not turn an extra valid read into StopIteration when the
    # suite's scheduling changes; the once-only navigation assertion below
    # remains the recovery invariant this test owns.
    snapshots = chain([stale], repeat(terminal))
    navigations: list[str] = []

    class FakeBrowser:
        class Page:
            url = chat.chat_url
            target_id = "target-1"

        async def page_by_handle(self, handle: str):
            return self.Page()

        async def navigate(self, page, url: str):
            navigations.append(url)

    chat.runtime = SimpleNamespace(gpt_browser=FakeBrowser())
    chat._binding_token_is_current = lambda _token: asyncio.sleep(0, result=True)  # type: ignore[method-assign]

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return next(snapshots)

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    result = False
    for _ in range(4):
        await asyncio.sleep(0.01)
        if await chat._reconcile_unresolved_turn():
            result = True
            break
    assert result is True, chat._unresolved_recovery_diagnostics()
    assert navigations == [chat.chat_url]


@pytest.mark.asyncio
async def test_reconcile_materializes_virtualized_completed_response_before_blocking_successor():
    """A completed background turn must not poison its persistent session.

    Live incident req_example_ed03bb215495d05f retained a fresh assistant id and
    terminal controls, but no assistant text.  The queued successor was then
    rejected as unresolved even though materializing the background tab would
    expose the completed response.
    """
    chat = _chat(response_stability_seconds=0.001)
    chat.unresolved_assistant_before_id = "a0"
    virtualized = ChatSnapshot(
        url="https://chatgpt.com/c/abc",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=2,
        latest_assistant_id="a1",
        latest_user_text="hi",
        latest_assistant_text=None,
        dom_signals=frozenset({"completion-control", "more-actions-menu"}),
        error_present=False,
        generating=False,
        latest_user_id="u1",
        user_message_ids=("u1",),
        user_message_texts=("hi",),
    )
    terminal = _terminal_snapshot(
        dom_signals=frozenset({"completion-control", "more-actions-menu"})
    )
    terminal = ChatSnapshot(
        **{
            **terminal.__dict__,
            "assistant_count": 2,
        }
    )
    snapshots = iter([virtualized, virtualized, terminal, terminal])
    materializations: list[bool] = []
    releases: list[bool] = []

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return next(snapshots)

    async def fake_materialize() -> bool:
        materializations.append(True)
        return True

    async def fake_release() -> None:
        releases.append(True)

    async def binding_current(_token) -> bool:
        return True

    async def fake_refresh() -> bool:
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.materialize_latest_assistant_turn = fake_materialize  # type: ignore[method-assign]
    chat.release_focus_emulation = fake_release  # type: ignore[method-assign]
    chat._refresh_for_reconciliation = fake_refresh  # type: ignore[method-assign]
    chat._binding_token_is_current = binding_current  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True
    assert materializations == [True]
    assert releases == [True]
    assert chat.unresolved_turn_pending is False


@pytest.mark.asyncio
async def test_ensure_ready_waits_for_stable_reconciliation_instead_of_failing_first_pass():
    chat = _chat(response_stability_seconds=0.001)
    chat.state = chat.state.RECOVERING
    observations = iter([False, True])
    calls: list[bool] = []

    async def fake_validate() -> None:
        return None

    async def fake_reconcile() -> bool:
        calls.append(True)
        reconciled = next(observations)
        if reconciled:
            chat.clear_unresolved_turn()
        else:
            chat._set_unresolved_recovery("awaiting-second-stable-observation")
        return reconciled

    chat._validate_page_binding = fake_validate  # type: ignore[method-assign]
    chat._reconcile_unresolved_turn = fake_reconcile  # type: ignore[method-assign]

    await chat.ensure_ready()

    assert len(calls) == 2
    assert chat.state.value == "ready"
    assert chat.unresolved_turn_pending is False


@pytest.mark.asyncio
async def test_restart_observer_bypasses_terminal_reconciliation_after_exact_rebind():
    """A resumed generating turn must enter the response observer directly."""
    chat = _chat(response_stability_seconds=0.001)
    chat.provider_session_id = "conversation-1"
    chat.state = ChatState.RECOVERING
    chat._defer_unresolved_reconciliation = True
    calls: list[bool] = []

    async def fake_validate() -> None:
        return None

    async def fail_reconcile() -> bool:
        calls.append(True)
        raise AssertionError("restart observer must not run terminal reconciliation")

    chat._validate_page_binding = fake_validate  # type: ignore[method-assign]
    chat._reconcile_unresolved_turn = fail_reconcile  # type: ignore[method-assign]

    await chat.ensure_ready()

    assert calls == []
    assert chat.state is ChatState.READY
    assert chat.unresolved_turn_pending is True


@pytest.mark.asyncio
async def test_quiescent_fresh_assistant_releases_session_when_response_body_stays_virtualized():
    updates = []
    awaited = []
    chat = _chat(response_stability_seconds=0.001)
    chat.provider_session_id = "conversation-1"
    chat.unresolved_assistant_before_id = "a0"
    class CustomAwaitable:
        def __await__(self):
            async def complete():
                awaited.append(True)

            return complete().__await__()

    def binding_sink(update):
        updates.append(update)
        return CustomAwaitable()

    chat.binding_sink = binding_sink
    virtualized = ChatSnapshot(
        url="https://chatgpt.com/c/conversation-1",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=2,
        latest_assistant_id="a1",
        latest_user_text="hi",
        latest_assistant_text=None,
        dom_signals=frozenset({"completion-control", "more-actions-menu"}),
        error_present=False,
        generating=False,
        latest_user_id="u1",
        user_message_ids=("u1",),
        user_message_texts=("hi",),
    )

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return virtualized

    async def no_materialization() -> bool:
        return False

    async def no_refresh() -> bool:
        return False

    async def binding_current(_token) -> bool:
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.materialize_latest_assistant_turn = no_materialization  # type: ignore[method-assign]
    chat._refresh_for_reconciliation = no_refresh  # type: ignore[method-assign]
    chat._binding_token_is_current = binding_current  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True
    assert chat.unresolved_turn_pending is False
    assert updates[-1].metadata == {
        "reconciliation-warning": "prior-response-text-unavailable",
        "reconciled-assistant-message-id": "a1",
    }
    assert awaited == [True]


@pytest.mark.asyncio
async def test_reconciliation_clear_is_persisted_before_memory_is_exposed_ready():
    chat = _chat(response_stability_seconds=0.001)
    snapshot = _terminal_snapshot(
        dom_signals=frozenset({"completion-control", "more-actions-menu"})
    )
    writes = []

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return snapshot

    async def checkpoint(metadata):
        writes.append((dict(metadata), chat.unresolved_turn_pending))

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.checkpoint_sink = checkpoint

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True
    assert writes == [({"unresolved-turn-pending": False, "submission-state": "cleared"}, True)]
    assert chat.unresolved_turn_pending is False
    reconstructed = PersistentChat(
        ag_session_id="session-restarted",
        project_name="project",
        project_url=None,
        runtime=object(),
        config=chat.config,
        binding_sink=lambda update: None,
        resume_provider_metadata={
            "unresolved-turn-pending": writes[-1][0]["unresolved-turn-pending"],
        },
    )
    assert reconstructed.unresolved_turn_pending is False


@pytest.mark.asyncio
async def test_durable_terminal_clear_removes_stale_unresolved_marker_without_dom_retry():
    chat = _chat(unresolved=True)
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-original"
    chat._checkpoint_metadata["terminal-evidence"] = {
        "turn-id": "req-original",
        "checkpoint-clear-persisted": True,
        "policy": "response-complete",
        "verification-evidence": [
            "assistant-fresh",
            "completion-control",
            "not-generating",
            "text-present",
        ],
    }
    writes = []

    async def checkpoint(metadata):
        writes.append(dict(metadata))

    chat.checkpoint_sink = checkpoint

    assert await chat._reconcile_unresolved_turn() is True
    assert chat.unresolved_turn_pending is False
    assert writes == [{"unresolved-turn-pending": False, "submission-state": "cleared"}]


@pytest.mark.asyncio
async def test_terminal_clear_from_different_turn_does_not_remove_unresolved_marker():
    chat = _chat(unresolved=True)
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-current"
    chat._checkpoint_metadata["terminal-evidence"] = {
        "turn-id": "req-older",
        "checkpoint-clear-persisted": True,
        "policy": "response-complete",
        "verification-evidence": [
            "completion-control",
            "not-generating",
            "text-present",
        ],
    }

    assert await chat._reconcile_unresolved_turn() is False
    assert chat.unresolved_turn_pending is True


@pytest.mark.asyncio
async def test_failed_durable_clear_keeps_unresolved_fence_in_memory(monkeypatch):
    from audiagentic.components.providers.adapters.gpt_auto import chat as chat_module
    clock = [1000.0]
    monkeypatch.setattr(chat_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    chat = _chat(response_stability_seconds=0.001)
    snapshot = _terminal_snapshot(
        dom_signals=frozenset({"completion-control", "more-actions-menu"})
    )

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return snapshot

    async def checkpoint(_metadata):
        raise OSError("disk unavailable")

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.checkpoint_sink = checkpoint

    assert await chat._reconcile_unresolved_turn() is False
    clock[0] += 1.0
    with pytest.raises(OSError, match="disk unavailable"):
        await chat._reconcile_unresolved_turn()
    assert chat.unresolved_turn_pending is True


@pytest.mark.asyncio
async def test_reconciliation_is_single_flight_for_concurrent_admission():
    chat = _chat(response_stability_seconds=0.001)
    chat.state = chat.state.RECOVERING
    active = 0
    maximum_active = 0
    calls = 0

    async def fake_validate() -> None:
        return None

    async def fake_reconcile() -> bool:
        nonlocal active, maximum_active, calls
        active += 1
        maximum_active = max(maximum_active, active)
        calls += 1
        await asyncio.sleep(0.005)
        if calls == 1:
            chat._set_unresolved_recovery("awaiting-second-stable-observation")
            result = False
        else:
            chat.clear_unresolved_turn()
            result = True
        active -= 1
        return result

    chat._validate_page_binding = fake_validate  # type: ignore[method-assign]
    chat._reconcile_unresolved_turn = fake_reconcile  # type: ignore[method-assign]

    await asyncio.gather(chat.ensure_ready(), chat.ensure_ready())
    assert maximum_active == 1
    assert calls == 2
    assert chat.state.value == "ready"


@pytest.mark.asyncio
async def test_reconciliation_deadline_bounds_hanging_observation():
    chat = _chat(response_stability_seconds=0.001)
    object.__setattr__(chat.config.chat, "ready_timeout_seconds", 0.02)
    chat.state = chat.state.RECOVERING

    async def fake_validate() -> None:
        return None

    async def hanging_reconcile() -> bool:
        await asyncio.sleep(60)
        return False

    chat._validate_page_binding = fake_validate  # type: ignore[method-assign]
    chat._reconcile_unresolved_turn = hanging_reconcile  # type: ignore[method-assign]

    with pytest.raises(Exception, match="could not reconcile the previous turn"):
        await chat.ensure_ready()
    assert chat._unresolved_recovery_reason == "reconciliation-readiness-timeout"


@pytest.mark.asyncio
async def test_admission_waits_for_busy_provider_then_reconciles_without_caller_retry():
    chat = _chat(response_stability_seconds=0.001)
    chat.state = chat.state.RECOVERING
    calls = 0

    async def fake_validate() -> None:
        return None

    async def fake_reconcile() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            chat._set_unresolved_recovery("provider-not-quiescent")
            return False
        chat.clear_unresolved_turn()
        return True

    chat._validate_page_binding = fake_validate  # type: ignore[method-assign]
    chat._reconcile_unresolved_turn = fake_reconcile  # type: ignore[method-assign]

    await chat.ensure_ready()
    assert calls == 2
    assert chat.state.value == "ready"


@pytest.mark.asyncio
async def test_hanging_warning_sink_cannot_block_durable_clear():
    chat = _chat(response_stability_seconds=0.001)
    chat.provider_session_id = "conversation-1"
    chat.unresolved_assistant_before_id = "a0"
    virtualized = ChatSnapshot(
        url="https://chatgpt.com/c/conversation-1",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=2,
        latest_assistant_id="a1",
        latest_user_text="hi",
        latest_assistant_text=None,
        dom_signals=frozenset({"completion-control", "more-actions-menu"}),
        error_present=False,
        generating=False,
        latest_user_id="u1",
        user_message_ids=("u1",),
        user_message_texts=("hi",),
    )
    durable = []

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return virtualized

    async def no_materialization() -> bool:
        return False

    async def no_refresh() -> bool:
        return False

    async def hanging_warning(_update):
        await asyncio.Event().wait()

    async def checkpoint(metadata):
        durable.append(dict(metadata))

    async def binding_current(_token) -> bool:
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.materialize_latest_assistant_turn = no_materialization  # type: ignore[method-assign]
    chat._refresh_for_reconciliation = no_refresh  # type: ignore[method-assign]
    chat.binding_sink = hanging_warning
    chat.checkpoint_sink = checkpoint
    chat._binding_token_is_current = binding_current  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await asyncio.wait_for(chat._reconcile_unresolved_turn(), timeout=2.0) is True
    assert durable == [{"unresolved-turn-pending": False, "submission-state": "cleared"}]
    assert chat.unresolved_turn_pending is False


@pytest.mark.asyncio
async def test_page_loss_after_durable_clear_becomes_page_recovery_not_turn_ambiguity():
    chat = _chat(response_stability_seconds=0.001)
    snapshot = _terminal_snapshot(
        dom_signals=frozenset({"completion-control", "more-actions-menu"})
    )
    writes = []
    chat.runtime = SimpleNamespace(release_page=lambda _chat, _handle: None)

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return snapshot

    async def checkpoint(metadata):
        writes.append(dict(metadata))
        if metadata == {"unresolved-turn-pending": False, "submission-state": "cleared"}:
            await chat.page_lost("page-1")

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.checkpoint_sink = checkpoint

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True
    assert chat.unresolved_turn_pending is False
    assert chat.page_handle is None
    assert writes == [{"unresolved-turn-pending": False, "submission-state": "cleared"}]
    assert await chat._reconciled_binding_is_current() is False


@pytest.mark.asyncio
async def test_same_target_navigation_before_clear_keeps_unresolved_fence():
    conversation_1 = "00000000-0000-4000-8000-ad40ca019414"
    conversation_2 = "00000000-0000-4000-8000-67835a5d984b"
    url_1 = f"https://chatgpt.com/g/g-p-project/c/{conversation_1}"
    url_2 = f"https://chatgpt.com/g/g-p-project/c/{conversation_2}"
    chat = _chat(response_stability_seconds=0.001)
    chat.provider_session_id = conversation_1
    chat.target_id = "target-1"
    snapshot = ChatSnapshot(
        **{**_terminal_snapshot(dom_signals=frozenset({"completion-control", "more-actions-menu"})).__dict__, "url": url_1}
    )
    writes = []

    class Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle, target_id="target-1", url=url_2)

    chat.runtime = SimpleNamespace(gpt_browser=Browser())

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return snapshot

    async def checkpoint(metadata):
        writes.append(dict(metadata))

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.checkpoint_sink = checkpoint

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is False
    assert chat._unresolved_recovery_reason == "provider-conversation-changed-during-reconciliation"
    assert chat.unresolved_turn_pending is True
    assert writes == []


@pytest.mark.asyncio
async def test_same_target_navigation_after_clear_blocks_ready_but_does_not_rearm_old_turn():
    conversation_1 = "00000000-0000-4000-8000-ad40ca019414"
    conversation_2 = "00000000-0000-4000-8000-67835a5d984b"
    url_1 = f"https://chatgpt.com/g/g-p-project/c/{conversation_1}"
    url_2 = f"https://chatgpt.com/g/g-p-project/c/{conversation_2}"
    current_url = url_1
    chat = _chat(response_stability_seconds=0.001)
    chat.provider_session_id = conversation_1
    chat.target_id = "target-1"
    chat.state = chat.state.RECOVERING
    snapshot = ChatSnapshot(
        **{**_terminal_snapshot(dom_signals=frozenset({"completion-control", "more-actions-menu"})).__dict__, "url": url_1}
    )
    writes = []

    class Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle, target_id="target-1", url=current_url)

    chat.runtime = SimpleNamespace(gpt_browser=Browser())

    async def fake_validate() -> None:
        return None

    async def fake_snapshot(*, allow_recovering: bool = False) -> ChatSnapshot:
        return snapshot

    async def checkpoint(metadata):
        nonlocal current_url
        writes.append(dict(metadata))
        current_url = url_2

    chat._validate_page_binding = fake_validate  # type: ignore[method-assign]
    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.checkpoint_sink = checkpoint

    with pytest.raises(RuntimeError, match="chat is not ready"):
        await chat.ensure_ready()
    assert writes == [{"unresolved-turn-pending": False, "submission-state": "cleared"}]
    assert chat.unresolved_turn_pending is False
    assert chat.state.value == "recovering"
