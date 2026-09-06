from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

from .test_greenfield_config_urls import valid_config


def _chat(*, response_stability_seconds: float = 6.0) -> PersistentChat:
    config_dict = valid_config()
    config_dict["turn"]["response-stability-seconds"] = response_stability_seconds
    chat = PersistentChat(
        ag_session_id="session-1",
        project_name="project",
        project_url=None,
        runtime=object(),  # unused: test snapshots are injected directly
        config=GptAutoConfig.from_dict(config_dict),
        binding_sink=lambda update: None,
        resume_provider_metadata={
            "unresolved-turn-pending": True,
            "prompt-message-id": "u1",
        },
    )
    chat.page_handle = "page-1"
    return chat


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
    chat = _chat(response_stability_seconds=0.001)
    chat.chat_url = "https://chatgpt.com/c/abc"
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
    snapshots = iter([stale, terminal, terminal])
    navigations: list[str] = []

    class FakeBrowser:
        async def page_by_handle(self, handle: str):
            return object()

        async def navigate(self, page, url: str):
            navigations.append(url)

    chat.runtime = SimpleNamespace(gpt_browser=FakeBrowser())

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

    Live incident req_634f7c5c595c496f retained a fresh assistant id and
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

    async def fake_refresh() -> bool:
        return True

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.materialize_latest_assistant_turn = fake_materialize  # type: ignore[method-assign]
    chat.release_focus_emulation = fake_release  # type: ignore[method-assign]
    chat._refresh_for_reconciliation = fake_refresh  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.01)
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
async def test_quiescent_fresh_assistant_releases_session_when_response_body_stays_virtualized():
    updates = []
    chat = _chat(response_stability_seconds=0.001)
    chat.provider_session_id = "conversation-1"
    chat.unresolved_assistant_before_id = "a0"
    chat.binding_sink = updates.append
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

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.materialize_latest_assistant_turn = no_materialization  # type: ignore[method-assign]
    chat._refresh_for_reconciliation = no_refresh  # type: ignore[method-assign]

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.01)
    assert await chat._reconcile_unresolved_turn() is True
    assert chat.unresolved_turn_pending is False
    assert updates[-1].metadata == {
        "reconciliation-warning": "prior-response-text-unavailable",
        "reconciled-assistant-message-id": "a1",
    }
