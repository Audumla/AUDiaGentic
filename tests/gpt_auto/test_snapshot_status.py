from __future__ import annotations

from audiagentic.components.providers.adapters.gpt_auto.snapshot import (
    ChatMessageRef,
    ChatSnapshot,
    PageObservationState,
)


def _snapshot(**overrides: object) -> ChatSnapshot:
    values: dict[str, object] = {
        "url": "https://chatgpt.com/g/g-p-test/project",
        "composer_present": True,
        "composer_editable": True,
        "user_count": 0,
        "assistant_count": 0,
        "latest_assistant_id": None,
        "latest_user_text": None,
        "latest_assistant_text": None,
        "dom_signals": frozenset(),
        "error_present": False,
        "generating": False,
    }
    values.update(overrides)
    return ChatSnapshot(**values)  # type: ignore[arg-type]


def test_page_observation_distinguishes_lifecycle_substates() -> None:
    baseline = _snapshot()

    assert _snapshot(url="", composer_present=False).observe().state is PageObservationState.LOADING
    assert (
        _snapshot(user_count=1, latest_user_text="review this").observe(baseline=baseline).state
        is PageObservationState.SUBMITTING
    )
    assert (
        _snapshot(generating=True, dom_signals=frozenset({"stop-control"})).observe(
            baseline=baseline
        ).state
        is PageObservationState.GENERATING
    )

    assistant = _snapshot(
        assistant_count=1,
        latest_assistant_id="a1",
        latest_assistant_text="partial review",
    )
    assert assistant.observe(baseline=baseline).state is PageObservationState.AWAITING_COMPLETION
    completed = _snapshot(
        assistant_count=1,
        latest_assistant_id="a1",
        latest_assistant_text="complete review",
        dom_signals=frozenset({"completion-control"}),
    )
    assert completed.observe(baseline=baseline).state is PageObservationState.COMPLETED


def test_page_observation_prioritizes_auth_and_failure_evidence() -> None:
    assert (
        _snapshot(dom_signals=frozenset({"auth-required"})).observe().state
        is PageObservationState.AUTH_REQUIRED
    )
    assert (
        _snapshot(error_present=True).observe().state is PageObservationState.FAILED
    )


def test_observation_mapping_is_sparse_but_keeps_evidence() -> None:
    mapping = _snapshot().observe().as_mapping()
    assert mapping["state"] == "ready"
    assert "markers" in mapping


def test_message_id_proves_a_fresh_prompt_even_when_virtualized_count_is_stable() -> None:
    baseline = _snapshot(user_count=4, latest_user_id="prompt-old", latest_user_text="old")
    current = _snapshot(user_count=4, latest_user_id="prompt-new", latest_user_text="new")

    observed = current.observe(baseline=baseline)

    assert "user-fresh" in observed.markers
    assert observed.state is PageObservationState.SUBMITTING


def test_bridge_snapshot_preserves_latest_user_message_id() -> None:
    snapshot = ChatSnapshot.from_bridge(
        {
            "url": "https://chatgpt.com/g/g-p-test/c/c1",
            "composerPresent": True,
            "composerEditable": True,
            "userCount": 2,
            "assistantCount": 1,
            "latestUserId": "prompt-2",
            "latestAssistantId": "answer-1",
            "latestUserText": "review",
            "latestAssistantText": "done",
        }
    )

    assert snapshot.latest_user_id == "prompt-2"


def test_bridge_snapshot_preserves_ordered_assistant_message_sequence() -> None:
    """GP08: the full ordered assistant sequence must survive the bridge
    round-trip, not just the single 'latest' projection -- this is the raw
    data a request-addressable correlation layer needs once more than one
    actor can post serially into the same conversation."""
    snapshot = ChatSnapshot.from_bridge(
        {
            "url": "https://chatgpt.com/g/g-p-test/c/c1",
            "composerPresent": True,
            "composerEditable": True,
            "userCount": 2,
            "assistantCount": 2,
            "latestUserId": "prompt-2",
            "latestAssistantId": "answer-2",
            "latestUserText": "second prompt",
            "latestAssistantText": "second answer",
            "assistantMessageIds": ["answer-1", "answer-2"],
            "assistantMessageTexts": ["first answer", "second answer"],
        }
    )

    assert snapshot.assistant_message_ids == ("answer-1", "answer-2")
    assert snapshot.assistant_message_texts == ("first answer", "second answer")


def test_bridge_snapshot_preserves_true_dom_order_across_roles() -> None:
    """GP08 slice 1: message_refs must preserve cross-role interleaving --
    the two legacy per-role arrays alone cannot distinguish 'assistant then
    a foreign user message' from 'foreign user message then assistant',
    which is exactly the ordering a request-scoped correlation boundary
    needs to resolve."""
    snapshot = ChatSnapshot.from_bridge(
        {
            "url": "https://chatgpt.com/g/g-p-test/c/c1",
            "composerPresent": True,
            "composerEditable": True,
            "userCount": 2,
            "assistantCount": 1,
            "latestUserId": "user-2",
            "latestAssistantId": "answer-1",
            "latestUserText": "second user message",
            "latestAssistantText": "the answer",
            "messageRefs": [
                {"role": "user", "messageId": "user-1", "text": "first user message", "sequence": 0},
                {"role": "assistant", "messageId": "answer-1", "text": "the answer", "sequence": 1},
                {"role": "user", "messageId": "user-2", "text": "second user message", "sequence": 2},
            ],
        }
    )

    assert snapshot.message_refs == (
        ChatMessageRef(role="user", message_id="user-1", text="first user message", sequence=0),
        ChatMessageRef(role="assistant", message_id="answer-1", text="the answer", sequence=1),
        ChatMessageRef(role="user", message_id="user-2", text="second user message", sequence=2),
    )
    # The assistant span ends at sequence 1: anything from sequence 2 onward
    # belongs to a later, foreign turn, regardless of role classification.
    assistant_index = next(
        i for i, ref in enumerate(snapshot.message_refs) if ref.role == "assistant"
    )
    boundary_index = next(
        (
            i
            for i, ref in enumerate(snapshot.message_refs)
            if i > assistant_index and ref.role == "user"
        ),
        None,
    )
    assert boundary_index == 2


def test_bridge_snapshot_defaults_assistant_sequence_to_empty_when_absent() -> None:
    """Older/minimal bridge payloads (e.g. hand-built test fixtures) that
    don't supply the new arrays must not error -- backward compatible."""
    snapshot = ChatSnapshot.from_bridge(
        {
            "url": "https://chatgpt.com/g/g-p-test/c/c1",
            "composerPresent": True,
            "composerEditable": True,
            "userCount": 1,
            "assistantCount": 1,
            "latestAssistantId": "answer-1",
        }
    )

    assert snapshot.assistant_message_ids == ()
    assert snapshot.assistant_message_texts == ()
