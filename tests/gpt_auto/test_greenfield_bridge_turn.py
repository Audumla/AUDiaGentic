from __future__ import annotations

from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot
from audiagentic.components.providers.adapters.gpt_auto.turn import (
    GptAutoTurn,
    TurnState,
    _facts,
)
from audiagentic.foundation.transports.agent_session import SessionPrompt

from .test_greenfield_config_urls import valid_config


def snap(
    *,
    users=0,
    assistants=0,
    user=None,
    assistant=None,
    assistant_id=None,
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


class _Chat:
    def __init__(self) -> None:
        self.ag_session_id = "ag-session-1"
        self.project_url = "https://chatgpt.com/g/g-p-project"
        self.provider_session_id = None
        self.chat_url = None
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
                )
                ,
                workflow=GptAutoConfig.from_dict(valid_config()).workflow,
            ),
        )
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

    async def snapshot(self):
        return next(self._snapshots)

    async def acquire_provider_identity(self, initial):
        self.provider_session_id = "conversation-1"
        self.chat_url = initial.url
        self.state = ChatState.BUSY
        return initial


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


@pytest.mark.asyncio
async def test_submitted_turn_cannot_reenter_submission():
    turn = GptAutoTurn(_Chat(), SessionPrompt(turn_id="turn-1", body="Review AU01"), lambda _: None)
    turn.state = TurnState.SUBMITTED
    turn.submission_confirmed = True
    with pytest.raises(RuntimeError):
        await turn._submit_once()


@pytest.mark.asyncio
async def test_composer_mismatch_fails_before_submission_can_be_accepted():
    chat = _Chat()
    chat.runtime.bridge = _Bridge("Cehra.l lBeen gceo nycoiusre .p")
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-1", body="Challenge your proposed order."), lambda _: None
    )
    turn.state = TurnState.SUBMITTING
    with pytest.raises(Exception, match="composer verification"):
        await turn._submit_once()
    assert not turn.submission_confirmed


@pytest.mark.asyncio
async def test_unproven_submission_fails_chat_instead_of_returning_empty_success():
    chat = _Chat()

    async def unchanged_snapshot():
        return snap()

    chat.snapshot = unchanged_snapshot
    chat.runtime.config.turn.submission_timeout_seconds = 0.01
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None
    )
    with pytest.raises(Exception, match="could not prove"):
        await turn.run()
    assert turn.state is TurnState.TIMED_OUT
    assert chat.state is ChatState.FAILED
    assert chat.runtime.bridge.submit_calls == 1
    assert chat.provider_session_id == "conversation-1"
    assert chat.chat_url.endswith("/c/conversation-1")


@pytest.mark.asyncio
async def test_inner_submission_timeout_is_not_mislabeled_as_absolute_timeout():
    chat = _Chat()
    chat.runtime.bridge = _TimeoutBridge()
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None
    )
    with pytest.raises(Exception, match="composer operation timed out"):
        await turn.run()
    assert turn.state is TurnState.FAILED
    assert chat.state is ChatState.FAILED


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
    with pytest.raises(Exception, match="failed response state"):
        await turn._await_response(snap(), snap(users=1, user="Review SH10"))
    assert chat.state is ChatState.FAILED


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
    assert not GptAutoConfig.from_dict(valid_config()).workflow.policy(
        "response-complete"
    ).evaluate(facts).satisfied


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
    assert chat.state is ChatState.FAILED


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
