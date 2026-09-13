from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot
from audiagentic.foundation.contracts.errors import AudiaGenticError

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


def test_recovery_transport_rejects_foreign_unresolved_request() -> None:
    chat = _chat()
    chat._checkpoint_metadata["unresolved-turn-id"] = "req-original"
    transport = GptAutoSessionTransport(chat)
    request = SimpleNamespace(turn_id="req-foreign")

    with pytest.raises(RuntimeError, match="does not belong to the recovered request"):
        asyncio.run(transport.resume_existing(request, lambda _observation: None))


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
    assert persisted == [{"unresolved-turn-pending": False}]


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
    snapshots = iter([stale, terminal, terminal])
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
    assert writes == [({"unresolved-turn-pending": False}, True)]
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
async def test_failed_durable_clear_keeps_unresolved_fence_in_memory():
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
    await asyncio.sleep(0.01)
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
    assert durable == [{"unresolved-turn-pending": False}]
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
        if metadata == {"unresolved-turn-pending": False}:
            await chat.page_lost("page-1")

    chat.snapshot = fake_snapshot  # type: ignore[method-assign]
    chat.checkpoint_sink = checkpoint

    assert await chat._reconcile_unresolved_turn() is False
    await asyncio.sleep(0.05)
    assert await chat._reconcile_unresolved_turn() is True
    assert chat.unresolved_turn_pending is False
    assert chat.page_handle is None
    assert writes == [{"unresolved-turn-pending": False}]
    assert await chat._reconciled_binding_is_current() is False


@pytest.mark.asyncio
async def test_same_target_navigation_before_clear_keeps_unresolved_fence():
    conversation_1 = "6a9d1f7a-199c-83ec-93a8-e1deafd5c1c7"
    conversation_2 = "6a9d1f7a-199c-83ec-93a8-e1deafd5c1c8"
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
    conversation_1 = "6a9d1f7a-199c-83ec-93a8-e1deafd5c1c7"
    conversation_2 = "6a9d1f7a-199c-83ec-93a8-e1deafd5c1c8"
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
    assert writes == [{"unresolved-turn-pending": False}]
    assert chat.unresolved_turn_pending is False
    assert chat.state.value == "recovering"
