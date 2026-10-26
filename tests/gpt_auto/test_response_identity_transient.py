import asyncio
from dataclasses import replace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.turn import (
    GptAutoTurn,
    TurnState,
    _empty_owned_response_identity_transient,
)
from audiagentic.foundation.transports.agent_session import SessionPrompt

from .test_greenfield_bridge_turn import _Chat, snap


def observations(*, replaced=False):
    baseline = snap(users=1, user="Request A", user_id="prompt-a")
    interim = snap(
        users=1,
        assistants=2,
        user="Request A",
        user_id="prompt-a",
        assistant_id="new",
        assistant="",
        complete=True,
    )
    prompt = replace(interim.message_refs[0], renderer_turn_id="turn-a")
    old = replace(
        interim.message_refs[1],
        message_id="old",
        text="Partial",
        renderer_turn_id="turn-a",
        renderer_unit_id="unit-a",
    )
    new = replace(old, message_id="new", text="", sequence=2)
    interim = replace(interim, message_refs=(prompt, old, new))
    terminal = replace(
        interim,
        latest_assistant_text="Definitive answer",
        message_refs=(prompt, old, replace(new, text="Definitive answer")),
    )
    if replaced:
        interim = replace(
            interim,
            assistant_count=1,
            message_refs=(
                replace(prompt, renderer_turn_id=None),
                replace(new, renderer_turn_id=None, renderer_unit_id=None),
            ),
        )
    return baseline, interim, terminal


def pending(baseline, interim):
    return _empty_owned_response_identity_transient(
        baseline,
        interim,
        prompt_message_id="prompt-a",
        prompt_text="Request A",
        bound_assistant_id="old",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("replaced", [False, True])
async def test_empty_candidate_retains_pin_then_captures_owned_terminal_without_send(replaced):
    baseline, interim, terminal = observations(replaced=replaced)
    chat = _Chat()
    chat.provider_session_id = "conversation-1"
    chat.chat_url = baseline.url
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="identity", body="Request A"), lambda _: None)
    turn.state = TurnState.AWAITING_RESPONSE
    turn._prompt_message_id = "prompt-a"
    turn._response_message_id = "old"
    seen = []

    async def snapshot():
        if not seen:
            seen.append("empty")
            return interim
        assert turn._response_message_id == ("old" if len(seen) == 1 else "new")
        seen.append("terminal")
        return terminal

    chat.snapshot = snapshot
    result = await asyncio.wait_for(turn._await_response(baseline, baseline), timeout=1)
    assert "Definitive answer" in result
    assert turn._response_message_id == "new"
    assert chat.runtime.bridge.submit_calls == 0
    assert seen.count("terminal") >= 2


@pytest.mark.parametrize(
    "mutation",
    [
        "url",
        "prompt",
        "foreign-user",
        "foreign-assistant",
        "baseline-old",
        "baseline-ref",
        "intervening-user",
        "markdown",
        "nonempty",
        "old-response",
        "no-prompt",
    ],
)
def test_transient_requires_explicit_request_and_renderer_correlation(mutation):
    baseline, interim, _ = observations()
    prompt, old, new = interim.message_refs
    if mutation == "url":
        interim = replace(interim, url="https://chatgpt.com/c/other")
    elif mutation == "prompt":
        interim = replace(interim, message_refs=(replace(prompt, text="Other request"), old, new))
    elif mutation == "foreign-user":
        interim = replace(
            interim,
            latest_user_id="foreign",
            message_refs=(prompt, old, replace(prompt, message_id="foreign"), new),
        )
    elif mutation == "foreign-assistant":
        interim = replace(
            interim, message_refs=(prompt, old, replace(new, renderer_turn_id="foreign"))
        )
    elif mutation == "intervening-user":
        interim = replace(
            interim, message_refs=(prompt, old, replace(prompt, message_id="foreign"), new)
        )
    elif mutation == "markdown":
        interim = replace(
            interim, message_refs=(prompt, old, replace(new, markdown="Foreign answer"))
        )
    elif mutation == "baseline-ref":
        baseline = replace(baseline, message_refs=(prompt, new))
    elif mutation == "baseline-old":
        baseline = replace(baseline, latest_assistant_id="new")
    elif mutation == "nonempty":
        interim = replace(
            interim,
            latest_assistant_text="Foreign answer",
            message_refs=(prompt, old, replace(new, text="Foreign answer")),
        )
    elif mutation == "old-response":
        interim = replace(interim, latest_assistant_id="old")
    else:
        interim = replace(interim, message_refs=(old, new), latest_user_id=None)
    assert not pending(baseline, interim)


def test_empty_sibling_is_only_uncertainty_not_terminal_proof():
    baseline, interim, terminal = observations()
    assert pending(baseline, interim)
    assert not pending(baseline, terminal)


@pytest.mark.asyncio
async def test_replaced_empty_candidate_remains_pending_until_cancel():
    baseline, interim, _ = observations(replaced=True)
    chat = _Chat()
    chat.provider_session_id = "conversation-1"
    chat.chat_url = baseline.url
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="identity", body="Request A"), lambda _: None)
    turn.state = TurnState.AWAITING_RESPONSE
    turn._prompt_message_id = "prompt-a"
    turn._response_message_id = "old"
    polls = 0

    async def snapshot():
        nonlocal polls
        polls += 1
        return interim

    chat.snapshot = snapshot
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(turn._await_response(baseline, baseline), timeout=0.03)
    assert polls > 1
    assert turn._response_message_id == "old"
    assert chat.runtime.bridge.submit_calls == 0
