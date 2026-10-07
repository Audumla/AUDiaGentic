from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from audiagentic.components.providers.adapters.gpt_auto.turn import GptAutoTurn, TurnState
from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat
from audiagentic.foundation.transports.agent_session import SessionPrompt

from .test_greenfield_bridge_turn import _Chat, snap


@pytest.mark.asyncio
async def test_submitted_load_error_retries_same_conversation_before_completion() -> None:
    chat = _Chat()
    chat.provider_session_id = "conversation-1"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation-1"
    baseline = snap(users=1, user="Review AU01")
    load_error = snap(
        users=1,
        user="Review AU01",
        composer_editable=False,
        extra_signals=("conversation-load-failed",),
    )
    answer = snap(
        users=1,
        assistants=1,
        user="Review AU01",
        assistant="done",
        assistant_id="12345678-1234-4234-8234-1234567890ab",
        complete=True,
    )
    chat._snapshots = iter([load_error, load_error, answer, answer, answer])
    chat.retry_conversation_load = AsyncMock(return_value=True)
    observations = []
    turn = GptAutoTurn(
        chat,
        SessionPrompt(turn_id="turn-load-retry", body="Review AU01"),
        observations.append,
    )
    turn._prompt_message_id = "prompt-1"
    turn.state = TurnState.AWAITING_RESPONSE
    turn.side_effect_attempted = True
    turn.submission_confirmed = True

    result = await turn._await_response_impl(baseline, baseline)

    assert result == "done"
    assert chat.retry_conversation_load.await_count == 2
    assert turn._conversation_load_retry_attempts == 0
    assert turn._conversation_load_retry_clicks == 2
    retry_events = [
        item.attributes
        for item in observations
        if item.kind.value == "timing"
        and str(item.attributes.get("timing-event", "")).startswith("conversation-load-")
    ]
    retry_details = [json.loads(event["diagnostic-details"]) for event in retry_events]
    assert [event["attempt"] for event in retry_details] == [1, 2]
    assert not any(
        getattr(item, "attributes", {}).get("model_activity")
        in {"conversation-load-retry-clicked", "conversation-load-observation-deferred"}
        for item in observations
    )


@pytest.mark.asyncio
async def test_retry_type_error_is_not_reinvoked_without_identity_fence() -> None:
    calls = []

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def retry_conversation_load(self, page, *, expected_path):
            calls.append((page.handle, expected_path))
            raise TypeError("provider evaluation failed")

    chat = object.__new__(PersistentChat)
    chat.page_handle = "page-1"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/conversation-1"
    chat.runtime = SimpleNamespace(gpt_browser=_Browser())

    with pytest.raises(TypeError, match="provider evaluation failed"):
        await chat.retry_conversation_load()

    assert calls == [("page-1", "/g/g-p-project/c/conversation-1")]
