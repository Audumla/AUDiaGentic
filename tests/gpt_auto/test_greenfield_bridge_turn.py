from __future__ import annotations

from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot
from audiagentic.components.providers.adapters.gpt_auto.turn import (
    GptAutoTurn,
    TurnState,
    _facts,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.agent_session import (
    ControlDisposition,
    SessionControlAction,
    SessionControlRequest,
    SessionFailureDisposition,
    SessionPrompt,
)

from .test_greenfield_config_urls import valid_config


def snap(
    *,
    users=0,
    assistants=0,
    user=None,
    assistant=None,
    assistant_id=None,
    user_id=None,
    generating=False,
    complete=False,
    extra_signals=(),
):
    signals = set(extra_signals)
    if generating:
        signals.add("stop-control")
    if complete:
        signals.add("completion-control")
    return ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/conversation-1",
        composer_present=True,
        composer_editable=True,
        user_count=users,
        assistant_count=assistants,
        latest_assistant_id=assistant_id or (f"assistant-{assistants}" if assistants else None),
        latest_user_text=user,
        latest_assistant_text=assistant,
        dom_signals=frozenset(signals),
        error_present=False,
        latest_user_id=user_id or (f"prompt-{users}" if users else None),
        # A real bridge observation derives both from the same underlying
        # DOM check (gpt_auto_cdp.py's raw `generating` query mirrors the
        # stop-control selectors) -- keep them coupled here so tests
        # exercise the real .generating field turn.py actually reads, not
        # just the decoupled dom_signals fact.
        generating=generating,
    )


class _Bridge:
    def __init__(self, typed_text: str | None = None) -> None:
        self.submit_calls = 0
        self.stop_calls = 0
        self.typed_text = typed_text

    async def call(self, method, params, **kwargs):
        if method == "submit_prompt":
            self.submit_calls += 1
            return {"actionComplete": True, "typedText": self.typed_text or params["text"]}
        if method == "stop_generation":
            self.stop_calls += 1
            return {"stopped": True}
        return {"ok": True}


class _TimeoutBridge(_Bridge):
    async def call(self, method, params, **kwargs):
        if method == "submit_prompt":
            self.submit_calls += 1
            raise TimeoutError
        return await super().call(method, params, **kwargs)


class _UnconfirmedBridge(_Bridge):
    async def call(self, method, params, **kwargs):
        if method == "submit_prompt":
            self.submit_calls += 1
            return {"actionComplete": False, "typedText": params["text"]}
        return await super().call(method, params, **kwargs)


class _Chat:
    def __init__(self) -> None:
        self.ag_session_id = "ag-session-1"
        self.project_url = "https://chatgpt.com/g/g-p-project"
        self.provider_session_id = None
        self.chat_url = None
        self.unresolved_prompt_message_id = None
        self.unresolved_assistant_before_id = None
        self.page_handle = "page-1"
        self.active_turn_id = None
        self.state = ChatState.READY
        self.runtime = SimpleNamespace(
            bridge=_Bridge(),
            config=SimpleNamespace(
                turn=SimpleNamespace(
                    submission_timeout_seconds=0.2,
                    response_start_timeout_seconds=0.2,
                    response_stall_timeout_seconds=0,
                    response_timeout_seconds=0.2,
                    response_stability_seconds=0,
                    poll_interval_seconds=0,
                ),
                workflow=GptAutoConfig.from_dict(valid_config()).workflow,
            ),
        )
        self.config = self.runtime.config
        self._snapshots = iter(
            [
                snap(),
                snap(users=1, user="Review AU01"),
                snap(users=1, user="Review AU01", generating=True),
                snap(users=1, assistants=1, user="Review AU01", assistant="Looks"),
                snap(users=1, assistants=1, user="Review AU01", assistant="Looks"),
                snap(
                    users=1,
                    assistants=1,
                    user="Review AU01",
                    assistant="Looks sound",
                    complete=True,
                ),
                snap(
                    users=1,
                    assistants=1,
                    user="Review AU01",
                    assistant="Looks sound",
                    complete=True,
                ),
                snap(
                    users=1,
                    assistants=1,
                    user="Review AU01",
                    assistant="Looks sound",
                    complete=True,
                ),
            ]
        )
        self.checkpoint_updates = []

    async def snapshot(self):
        return next(self._snapshots)

    async def acquire_provider_identity(self, initial):
        self.provider_session_id = "conversation-1"
        self.chat_url = initial.url
        self.state = ChatState.BUSY
        return initial

    def mark_submission_unresolved(self, prompt_text=None):
        self.unresolved_turn_pending = True
        self.prompt_text = prompt_text

    def mark_prompt_submitted(self, prompt_id, assistant_before_id, prompt_text=None):
        self.unresolved_turn_pending = True
        self.unresolved_prompt_message_id = prompt_id
        self.unresolved_assistant_before_id = assistant_before_id
        self.prompt_text = prompt_text

    def clear_unresolved_turn(self):
        self.unresolved_turn_pending = False

    async def persist_unresolved_checkpoint(self, *, turn_id, baseline):
        self.checkpoint_updates.append(
            {
                "turn-id": turn_id,
                "recovery-state": "side-effect-may-have-started",
                "unresolved-turn-pending": True,
                "baseline-user-id": baseline.latest_user_id,
            }
        )

    async def persist_unresolved_clear(self):
        self.checkpoint_updates.append({"unresolved-turn-pending": False})


@pytest.mark.asyncio
async def test_turn_proves_submission_once_and_completes_from_atomic_snapshots():
    chat = _Chat()
    observations = []
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-1", body="Review AU01"), observations.append
    )
    result = await turn.run()
    assert result.stop_reason == "end-turn"
    assert result.final_summary == "Looks sound"
    assert chat.runtime.bridge.submit_calls == 1
    assert turn.submission_confirmed
    assert turn.state is TurnState.COMPLETE
    assert chat.state is ChatState.READY
    assert result.metadata["prompt-message-id"] == "prompt-1"
    assert result.metadata["assistant-message-id"] == "assistant-1"
    assert chat.checkpoint_updates[0]["recovery-state"] == "side-effect-may-have-started"
    assert chat.checkpoint_updates[-1] == {"unresolved-turn-pending": False}


@pytest.mark.asyncio
async def test_turn_completes_despite_stuck_stop_control_signal():
    """Live-reproduced 2026-08-16: ChatGPT's own stop/submit button can stay
    in its 'stop' state indefinitely after a response has actually finished
    rendering. generating=True (and the stop-control dom signal) must be
    advisory-only, never an unconditional veto -- a stable, corroborated
    response-complete result must still terminate the turn."""
    chat = _Chat()
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01", generating=True),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Looks",
                generating=True,
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Looks sound",
                generating=True,
                complete=True,
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Looks sound",
                generating=True,
                complete=True,
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Looks sound",
                generating=True,
                complete=True,
            ),
        ]
    )
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-stuck-stop-control", body="Review AU01"), lambda _: None
    )
    result = await turn.run()
    assert result.stop_reason == "end-turn"
    assert result.final_summary == "Looks sound"
    assert turn.state is TurnState.COMPLETE


@pytest.mark.asyncio
async def test_turn_does_not_complete_while_text_is_still_changing_even_without_generating_veto():
    """Regression guard for the fix above: removing the generating veto must
    not turn this into a false-positive-completion risk. Text still actively
    changing (no stability window satisfied) must keep blocking completion
    regardless of what any DOM widget claims, and must still time out
    correctly rather than falsely declare success."""
    chat = _Chat()
    chat.runtime.config.turn.response_timeout_seconds = 0.05
    chat.runtime.config.turn.response_start_timeout_seconds = 0.05

    def _growing_text_snapshots():
        prefix = "Looks sound"
        counter = 0
        while True:
            counter += 1
            yield snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant=f"{prefix} {counter}",
                complete=True,
            )

    chat._snapshots = _growing_text_snapshots()
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-still-changing", body="Review AU01"), lambda _: None
    )
    with pytest.raises(AudiaGenticError):
        await turn.run()
    assert turn.state is not TurnState.COMPLETE


@pytest.mark.asyncio
async def test_prompt_and_response_message_ids_are_published_for_resume_metadata():
    chat = _Chat()
    updates = []
    chat.binding_sink = lambda update: updates.append(update)
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-identities", body="Review AU01"), lambda _: None
    )

    await turn.run()

    assert any(update.metadata.get("prompt-message-id") == "prompt-1" for update in updates)
    assert any(update.metadata.get("assistant-message-id") == "assistant-1" for update in updates)


@pytest.mark.asyncio
async def test_post_submit_observer_failure_preserves_phase_and_cause():
    chat = _Chat()

    def failed_sink(_observation):
        raise ValueError("observer lease is stale")

    turn = GptAutoTurn(
        chat,
        SessionPrompt(turn_id="turn-observer", body="Review AU01"),
        failed_sink,
    )

    with pytest.raises(AudiaGenticError) as captured:
        await turn.run()

    error = captured.value
    assert error.code == "EXT-GPTAUTO-004"
    assert "turn-accepted-observation" in error.message
    assert "ValueError: observer lease is stale" in error.message
    assert error.details["phase"] == "turn-accepted-observation"
    assert error.details["cause-type"] == "ValueError"
    assert error.details["submission-proven"] is True


@pytest.mark.asyncio
async def test_submitted_turn_cannot_reenter_submission():
    turn = GptAutoTurn(_Chat(), SessionPrompt(turn_id="turn-1", body="Review AU01"), lambda _: None)
    turn.state = TurnState.SUBMITTED
    turn.submission_confirmed = True
    with pytest.raises(RuntimeError):
        await turn._submit_once()


@pytest.mark.asyncio
async def test_composer_mismatch_waits_for_authoritative_submission_proof():
    chat = _Chat()
    chat.runtime.bridge = _Bridge("Cehra.l lBeen gceo nycoiusre .p")
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-1", body="Challenge your proposed order."), lambda _: None
    )
    turn.state = TurnState.SUBMITTING
    await turn._submit_once()
    assert not turn.submission_confirmed
    assert turn._composer_verification_mismatch == {
        "failure-reason": "composer-typed-text-mismatch",
        "typed-text-length": len("Cehra.l lBeen gceo nycoiusre .p"),
        "typed-text-match": False,
    }


@pytest.mark.asyncio
async def test_composer_readback_mismatch_does_not_duplicate_when_prompt_is_proven():
    chat = _Chat()
    chat.runtime.bridge = _Bridge("formatting differs in the editor surface")
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-1", body="Review AU01"), lambda _: None
    )

    result = await turn.run()

    assert result.stop_reason == "end-turn"
    assert turn.submission_confirmed
    assert chat.runtime.bridge.submit_calls == 1


@pytest.mark.asyncio
async def test_unproven_submission_fails_chat_instead_of_returning_empty_success():
    chat = _Chat()

    async def unchanged_snapshot():
        return snap()

    chat.snapshot = unchanged_snapshot
    chat.runtime.config.turn.submission_timeout_seconds = 0.01
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None)
    with pytest.raises(Exception, match="could not prove"):
        await turn.run()
    assert turn.state is TurnState.TIMED_OUT
    assert chat.state is ChatState.FAILED
    assert chat.runtime.bridge.submit_calls == 1
    assert chat.provider_session_id == "conversation-1"
    assert chat.chat_url.endswith("/c/conversation-1")


@pytest.mark.asyncio
async def test_ambiguous_resume_captures_prompt_id_when_provider_identity_is_known():
    chat = _Chat()
    chat.provider_session_id = "conversation-1"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation-1"
    chat._snapshots = iter([snap(users=1, user="Review SH10", user_id="fresh-user")])
    updates = []
    chat.binding_sink = lambda update: updates.append(update)
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-known-resume", body="Review SH10"), lambda _: None)
    turn._baseline_snapshot = snap()

    await turn._capture_provider_identity_after_ambiguous_submission()

    assert turn._prompt_message_id == "fresh-user"
    assert chat.unresolved_prompt_message_id == "fresh-user"
    assert any(update.metadata.get("prompt-message-id") == "fresh-user" for update in updates)


@pytest.mark.asyncio
async def test_unproven_submission_failure_keeps_bounded_last_observation_evidence():
    chat = _Chat()

    async def unchanged_snapshot():
        return snap(users=0, assistants=0, extra_signals=("loading",))

    chat.snapshot = unchanged_snapshot
    chat.runtime.config.turn.submission_timeout_seconds = 0.01
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-diagnostics", body="Review SH10"), lambda _: None
    )

    with pytest.raises(AudiaGenticError) as captured:
        await turn.run()

    details = captured.value.details
    assert details["failure-reason"] == "submission-proof-not-observed-before-deadline"
    assert details["observation-state"] == "ready"
    assert details["observed-user-count"] == 0
    assert details["prompt-text-match"] is False
    assert "latest-user-text" not in details
    assert "latest-assistant-text" not in details


@pytest.mark.asyncio
async def test_inner_submission_timeout_is_not_mislabeled_as_absolute_timeout():
    chat = _Chat()
    chat.runtime.bridge = _TimeoutBridge()
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None)
    with pytest.raises(Exception, match="composer operation timed out"):
        await turn.run()
    assert turn.state is TurnState.FAILED
    assert chat.state is ChatState.FAILED


@pytest.mark.asyncio
async def test_unconfirmed_composer_action_fails_with_action_reason():
    chat = _Chat()
    chat.runtime.bridge = _UnconfirmedBridge()
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-action-unconfirmed", body="Review"), lambda _: None
    )
    turn.state = TurnState.SUBMITTING

    with pytest.raises(AudiaGenticError) as captured:
        await turn._submit_once()

    assert captured.value.details["failure-reason"] == "composer-action-not-confirmed"
    assert captured.value.details["action-complete"] is False


@pytest.mark.asyncio
async def test_real_chat_transition_is_terminalized_exactly_once_on_policy_failure():
    chat = _Chat()
    transitions = []

    def move(state):
        if chat.state is state:
            raise RuntimeError("duplicate transition")
        transitions.append((chat.state, state))
        chat.state = state

    chat._move = move
    failed = snap(users=1, user="Review SH10", extra_signals=("error-page",))
    chat._snapshots = iter([snap(), snap(users=1, user="Review SH10"), failed])
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None)

    with pytest.raises(Exception, match="provider failure policy matched"):
        await turn.run()

    assert transitions.count((ChatState.BUSY, ChatState.FAILED)) == 1


def test_prompt_identity_preserves_case_spacing_and_indentation():
    from audiagentic.components.providers.adapters.gpt_auto.turn import _normal

    assert _normal("Return Foo") != _normal("return foo")
    assert _normal("x  y") != _normal("x y")
    assert _normal("if ok:\n    run()") != _normal("if ok:\nrun()")
    assert _normal("line\r\n") == "line"


@pytest.mark.asyncio
async def test_configured_dom_failure_policy_fails_the_workflow():
    chat = _Chat()
    failed = snap(users=1, user="Review SH10", extra_signals=("error-page",))

    async def failed_snapshot():
        return failed

    chat.snapshot = failed_snapshot
    chat.state = ChatState.BUSY
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None)
    turn.state = TurnState.AWAITING_RESPONSE
    with pytest.raises(Exception, match="provider failure policy matched"):
        await turn._await_response(snap(), snap(users=1, user="Review SH10"))
    # Inner response policy owns only the turn terminal state.  run() is the
    # single owner of chat terminalisation, preventing FAILED -> FAILED.
    assert chat.state is ChatState.BUSY


@pytest.mark.asyncio
async def test_provider_failure_policy_keeps_dom_evidence_without_message_bodies():
    chat = _Chat()
    failed = snap(users=1, user="Review SH10", extra_signals=("error-page",))

    async def failed_snapshot():
        return failed

    chat.snapshot = failed_snapshot
    chat.state = ChatState.BUSY
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-failure-evidence", body="Review SH10"), lambda _: None)
    turn.state = TurnState.AWAITING_RESPONSE

    with pytest.raises(AudiaGenticError, match="provider failure policy matched") as captured:
        await turn._await_response(snap(), snap(users=1, user="Review SH10"))

    details = captured.value.details
    assert details["failure-reason"] == "provider-failure-policy-matched"
    assert details["observation-state"] == "failed"
    assert "latest-user-text" not in details
    assert "latest-assistant-text" not in details


def test_old_assistant_text_mutation_is_not_a_fresh_response():
    baseline = snap(
        users=1,
        assistants=1,
        user="Review SH10",
        assistant="Original response",
        assistant_id="assistant-existing",
        complete=True,
    )
    mutated = snap(
        users=2,
        assistants=1,
        user="Continue the review",
        assistant="Original response Sources",
        assistant_id="assistant-existing",
        complete=True,
    )
    facts = _facts(baseline, baseline, mutated)
    assert not facts["assistant-fresh"]
    assert (
        not GptAutoConfig.from_dict(valid_config())
        .workflow.policy("response-complete")
        .evaluate(facts)
        .satisfied
    )


@pytest.mark.asyncio
async def test_response_start_timeout_is_a_named_policy_not_total_completion_timeout():
    chat = _Chat()
    waiting = snap(users=1, user="Review SH10")

    async def waiting_snapshot():
        return waiting

    chat.snapshot = waiting_snapshot
    chat.runtime.config.turn.response_start_timeout_seconds = 0.01
    chat.runtime.config.turn.response_timeout_seconds = 1
    chat.state = ChatState.BUSY
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None)
    turn.state = TurnState.AWAITING_RESPONSE
    with pytest.raises(Exception) as exc_info:
        await turn._await_response(snap(), waiting)
    assert exc_info.value.details["timeout-policy"] == "response-start-timeout"
    assert turn.state is TurnState.TIMED_OUT
    assert chat.state is ChatState.BUSY


@pytest.mark.asyncio
async def test_cancellation_is_terminal_and_never_retries_submit():
    chat = _Chat()
    turn = GptAutoTurn(
        chat,
        SessionPrompt(turn_id="turn-1", body="Review AU01"),
        lambda _: None,
    )
    turn.cancel()
    result = await turn.run()
    assert result.stop_reason == "cancelled"
    assert turn.state is TurnState.CANCELLED
    assert chat.runtime.bridge.submit_calls == 0
    await turn._stop_task
    assert chat.runtime.bridge.stop_calls == 1


@pytest.mark.asyncio
async def test_cancel_after_submit_blocks_ready_when_quiescence_is_unproven():
    chat = _Chat()

    async def not_quiescent():
        raise RuntimeError("still generating")

    chat.wait_quiescent = not_quiescent
    chat.state = ChatState.BUSY
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review"), lambda _: None)
    turn.state = TurnState.GENERATING
    turn.side_effect_attempted = True

    turn.cancel()
    await turn._stop_task

    assert chat.state is ChatState.RECOVERING
    assert chat.runtime.bridge.stop_calls == 1


@pytest.mark.asyncio
async def test_delayed_cancel_for_old_turn_does_not_cancel_active_turn():
    chat = _Chat()
    transport = GptAutoSessionTransport(chat)
    active = GptAutoTurn(chat, SessionPrompt(turn_id="turn-2", body="Next"), lambda _: None)
    transport._active_turn = active
    request = SessionControlRequest(
        ag_session_id=chat.ag_session_id,
        turn_id="turn-1",
        action=SessionControlAction.CANCEL_TURN,
    )

    result = await transport.control(request)

    assert result.disposition is ControlDisposition.ALREADY_TERMINAL
    assert not active.cancel_event.is_set()


@pytest.mark.asyncio
async def test_admission_failure_marks_recoverable_session_for_gateway_retention():
    chat = _Chat()
    admission_error = AudiaGenticError(
        code="EXT-GPTAUTO-004",
        kind="providers",
        message="previous turn outcome is unresolved",
    )

    async def ensure_ready():
        raise admission_error

    async def retain_after_turn_failure(error):
        assert error is admission_error
        return True

    chat.ensure_ready = ensure_ready
    chat.retain_after_turn_failure = retain_after_turn_failure
    transport = GptAutoSessionTransport(chat)

    with pytest.raises(AudiaGenticError, match="previous turn outcome"):
        await transport.prompt(SessionPrompt(turn_id="turn-1", body="continue"), lambda _: None)

    assert transport.turn_failure_disposition() is SessionFailureDisposition.RETAIN
