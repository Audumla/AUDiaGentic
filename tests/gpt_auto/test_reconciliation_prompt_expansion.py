"""Collapsed user prompts require full fingerprint proof, never count/ID proof."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import PromptFingerprint
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatMessageRef

from .test_chat_unresolved_reconciliation import _chat, _terminal_snapshot

FULL = "source prefix\nprivate hidden middle with request-specific instructions\nsource suffix"
COLLAPSED = "source prefix\nsource suffix"
URL = "https://chatgpt.com/g/g-p-project/c/abc"
SIGNALS = frozenset({"completion-control", "more-actions-menu", "response-complete-status"})


def case():
    chat = _chat(response_stability_seconds=0.001)
    chat.state = ChatState.RECOVERING
    chat.chat_url = URL
    chat.provider_session_id = "abc"
    chat.target_id = "target-1"
    chat.unresolved_prompt_message_id = None
    chat.unresolved_assistant_message_id = None
    chat.unresolved_assistant_before_id = "a-before"
    chat.unresolved_prompt_text_digest = PromptFingerprint.from_text(FULL).digest
    chat._checkpoint_metadata.update({
        "unresolved-turn-id": "request-1", "submission-attempt-id": "attempt-1",
        "unresolved-baseline-user-id": "u-before",
        "unresolved-baseline-user-count": 5, "unresolved-baseline-assistant-count": 6,
    })
    state = SimpleNamespace(expanded=False, calls=[], outcome=True, after=None, writes=[])

    def observed(text):
        return replace(_terminal_snapshot(dom_signals=SIGNALS),
            url=URL, user_count=5, assistant_count=6, latest_user_id="u-new",
            latest_assistant_id="a-new", latest_user_text=text,
            user_message_ids=("u-before", "u-new"), user_message_texts=("previous", text),
            terminal_witness_assistant_id="a-new",
            message_refs=(ChatMessageRef("user", "u-before", "previous", 0),
                          ChatMessageRef("assistant", "a-before", "old answer", 1),
                          ChatMessageRef("user", "u-new", text, 2, correlation_text=text),
                          ChatMessageRef("assistant", "a-new", "response text", 3)))

    state.before = observed(COLLAPSED)
    state.after = observed(FULL)
    page = SimpleNamespace(handle=chat.page_handle, target_id=chat.target_id, url=URL)

    async def page_by_handle(handle):
        assert handle == chat.page_handle
        return page

    async def expand(page_arg, message_id):
        assert page_arg is page
        state.calls.append(message_id)
        if isinstance(state.outcome, Exception):
            raise state.outcome
        state.expanded = bool(state.outcome)
        return state.outcome

    async def snapshot(**kwargs):
        assert kwargs == {"allow_recovering": True}
        return state.after if state.expanded else state.before

    async def forbidden(*args, **kwargs):
        pytest.fail("recovery must not send, navigate, focus, refresh or materialize")

    async def persist():
        state.writes.append("clear")

    chat.runtime = SimpleNamespace(gpt_browser=SimpleNamespace(
        page_by_handle=page_by_handle, expand_user_prompt=expand))
    chat.snapshot = snapshot
    chat._refresh_for_reconciliation = forbidden
    chat.materialize_latest_assistant_turn = forbidden
    chat.retry_delivery_timeout = forbidden
    chat.persist_unresolved_clear = persist
    return chat, state, page


@pytest.mark.asyncio
async def test_hidden_middle_expands_then_requires_existing_stable_terminal_proof():
    chat, state, _ = case()
    assert not await chat._reconcile_unresolved_turn()
    assert state.calls == ["u-new"]
    assert chat.unresolved_turn_pending and not state.writes
    # Advance the existing stability candidate, without sleeping or changing policy.
    chat._unresolved_match_fingerprint_at -= 1
    assert await chat._reconcile_unresolved_turn()
    assert state.calls == ["u-new"] and state.writes == ["clear"]
    assert not chat.unresolved_turn_pending


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, RuntimeError("private detail")])
async def test_expansion_failure_is_one_shot_and_retains_fence(failure):
    chat, state, _ = case()
    state.outcome = failure
    for _ in range(2):
        assert not await chat._reconcile_unresolved_turn()
    assert state.calls == ["u-new"]
    assert chat.unresolved_turn_pending and not state.writes


@pytest.mark.asyncio
async def test_wrong_hidden_middle_never_matches_even_after_expansion():
    chat, state, _ = case()
    wrong = FULL.replace("request-specific", "unrelated")
    state.after = replace(state.after, latest_user_text=wrong,
        user_message_texts=("previous", wrong),
        message_refs=tuple(replace(ref, text=wrong, correlation_text=wrong)
                           if ref.message_id == "u-new" else ref for ref in state.after.message_refs))
    for _ in range(2):
        assert not await chat._reconcile_unresolved_turn()
    assert state.calls == ["u-new"]
    assert chat.unresolved_turn_pending and not state.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["many-fresh", "missing-baseline", "wrong-url", "wrong-target", "dead-owner", "missing-attempt"])
async def test_unowned_or_ambiguous_prompt_is_not_expanded(change):
    chat, state, page = case()
    if change == "many-fresh":
        state.before = replace(state.before, message_refs=state.before.message_refs[:2] +
            (ChatMessageRef("user", "foreign", "another request", 2),) + state.before.message_refs[2:])
    elif change == "missing-baseline":
        state.before = replace(state.before, message_refs=state.before.message_refs[1:])
    elif change == "wrong-url":
        state.before = replace(state.before, url="https://chatgpt.com/g/g-p-project/c/foreign")
    elif change == "wrong-target":
        page.target_id = "foreign-target"
    elif change == "dead-owner":
        chat.set_page_mutation_owner_probe(lambda: False)
    else:
        chat._checkpoint_metadata.pop("submission-attempt-id")
    assert not await chat._reconcile_unresolved_turn()
    assert not state.calls and not state.writes and chat.unresolved_turn_pending


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["wrong-url", "assistant-changed", "foreign-user", "request-replaced"])
async def test_post_expansion_drift_retains_fence(change):
    chat, state, _ = case()
    original = chat.runtime.gpt_browser.expand_user_prompt

    async def expand(*args):
        result = await original(*args)
        if change == "request-replaced":
            chat._checkpoint_metadata = {**chat._checkpoint_metadata, "submission-attempt-id": "successor"}
        return result

    chat.runtime.gpt_browser.expand_user_prompt = expand
    if change == "wrong-url":
        state.after = replace(state.after, url="https://chatgpt.com/g/g-p-project/c/foreign")
    elif change == "assistant-changed":
        state.after = replace(state.after, latest_assistant_id="foreign-assistant")
    elif change == "foreign-user":
        state.after = replace(state.after, latest_user_id="foreign-user")
    assert not await chat._reconcile_unresolved_turn()
    assert not state.writes and chat.unresolved_turn_pending


@pytest.mark.asyncio
async def test_expanded_matching_prompt_without_terminal_controls_stays_pending():
    chat, state, _ = case()
    state.before = replace(state.before, dom_signals=frozenset())
    state.after = replace(state.after, dom_signals=frozenset())
    assert not await chat._reconcile_unresolved_turn()
    assert not await chat._reconcile_unresolved_turn()
    assert chat.unresolved_turn_pending and not state.writes


@pytest.mark.asyncio
async def test_generating_collapsed_prompt_is_not_expanded_or_cleared():
    chat, state, _ = case()
    state.before = replace(state.before, generating=True)
    assert not await chat._reconcile_unresolved_turn()
    assert not state.calls and not state.writes and chat.unresolved_turn_pending


@pytest.mark.asyncio
async def test_attempt_handoff_during_page_lookup_prevents_expansion():
    chat, state, _ = case()
    browser = chat.runtime.gpt_browser
    original = browser.page_by_handle

    async def lookup(handle):
        page = await original(handle)
        chat._checkpoint_metadata = {**chat._checkpoint_metadata, "submission-attempt-id": "successor"}
        return page

    browser.page_by_handle = lookup
    assert not await chat._reconcile_unresolved_turn()
    assert not state.calls and not state.writes and chat.unresolved_turn_pending


@pytest.mark.asyncio
async def test_authentication_veto_prevents_prompt_expansion():
    chat, state, _ = case()
    state.before = replace(state.before, dom_signals=SIGNALS | {"auth-required"})
    assert not await chat._reconcile_unresolved_turn()
    assert not state.calls and not state.writes and chat.unresolved_turn_pending


@pytest.mark.asyncio
async def test_already_matching_prompt_uses_existing_proof_without_expansion():
    chat, state, _ = case()
    state.before = state.after
    assert not await chat._reconcile_unresolved_turn()
    chat._unresolved_match_fingerprint_at -= 1
    assert await chat._reconcile_unresolved_turn()
    assert not state.calls and state.writes == ["clear"]


@pytest.mark.asyncio
async def test_attempt_handoff_during_post_expansion_binding_check_retains_fence():
    chat, state, _ = case()
    browser = chat.runtime.gpt_browser
    original = browser.page_by_handle

    async def lookup(handle):
        page = await original(handle)
        if state.expanded:
            chat._checkpoint_metadata = {**chat._checkpoint_metadata, "submission-attempt-id": "successor"}
        return page

    browser.page_by_handle = lookup
    assert not await chat._reconcile_unresolved_turn()
    assert state.calls == ["u-new"] and not state.writes and chat.unresolved_turn_pending
