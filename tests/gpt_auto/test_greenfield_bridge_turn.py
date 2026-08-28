from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatMessageRef, ChatSnapshot
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
    composer_editable=True,
    tool_activity_counts=(),
    user_correlation=None,
    structural_hr_count=0,
):
    signals = set(extra_signals)
    if generating:
        signals.add("stop-control")
    if complete:
        # GP17/GP32: response-complete requires completion-control AND a
        # corroborating partner together (all-of, not any-of) -- either
        # alone was proven live-unreliable. That partner was
        # Renderer-position markers (data-is-last-node/data-is-only-node) are
        # deliberately not used: they can appear while output is still
        # streaming. Set the independently validated action-bar pair so
        # `complete=True` means "genuinely done" in happy-path fixtures.
        signals.add("completion-control")
        signals.add("more-actions-menu")
    resolved_user_id = user_id or (f"prompt-{users}" if users else None)
    resolved_assistant_id = assistant_id or (f"assistant-{assistants}" if assistants else None)
    # GP30: message_refs is the true-DOM-order sequence _await_response()'s
    # resolver keys off of -- populate it from this snapshot's own latest
    # user/assistant pair so single-turn test fixtures exercise the same
    # request-scoped correlation real bridge snapshots do (GP29).  Only the
    # single latest pair is representable here; tests that need to model a
    # foreign/later turn build message_refs explicitly themselves.
    message_refs: list[ChatMessageRef] = []
    if users and resolved_user_id:
        message_refs.append(
            ChatMessageRef(
                role="user",
                message_id=resolved_user_id,
                text=user,
                correlation_text=user_correlation,
                structural_hr_count=structural_hr_count,
                sequence=0,
            )
        )
    if assistants and resolved_assistant_id:
        message_refs.append(
            ChatMessageRef(role="assistant", message_id=resolved_assistant_id, text=assistant, sequence=1)
        )
    return ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/conversation-1",
        composer_present=True,
        composer_editable=composer_editable,
        user_count=users,
        assistant_count=assistants,
        latest_assistant_id=resolved_assistant_id,
        latest_user_text=user,
        latest_assistant_text=assistant,
        dom_signals=frozenset(signals),
        error_present=False,
        latest_user_id=resolved_user_id,
        # A real bridge observation derives both from the same underlying
        # DOM check (gpt_auto_cdp.py's raw `generating` query mirrors the
        # stop-control selectors) -- keep them coupled here so tests
        # exercise the real .generating field turn.py actually reads, not
        # just the decoupled dom_signals fact.
        generating=generating,
        message_refs=tuple(message_refs),
        tool_activity_counts=tuple(tool_activity_counts),
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
                    submission_proof_progress_lease_seconds=0.2,
                    submission_proof_absolute_ceiling_seconds=1.0,
                ),
                workflow=GptAutoConfig.from_dict(valid_config()).workflow,
            ),
        )
        self.config = self.runtime.config
        self._snapshots = iter(
            [
                snap(),
                snap(users=1, user="Review AU01"),
                # GP07: submission-proof now takes one confirming poll before
                # VERIFIED_TERMINAL (the whole point -- a single observation
                # is no longer trusted alone), so this duplicate gives that
                # tick room without shifting every other snapshot's meaning.
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
async def test_await_response_never_returns_a_later_foreign_turns_answer():
    """GP08/GP30 core regression: once a later, unrelated turn (from any
    actor -- a human typing in the same tab, or a later gateway request)
    posts into the same conversation, its assistant reply must never be
    mistaken for THIS request's own answer, even after it becomes
    conversation-global-latest. Before GP30, _await_response() biased
    toward whatever ChatSnapshot.latest_assistant_id/_text reported, which
    would have returned the foreign answer here."""
    chat = _Chat()

    own_prompt_ref = ChatMessageRef(role="user", message_id="prompt-1", text="Review AU01", sequence=0)
    own_answer_ref = ChatMessageRef(role="assistant", message_id="assistant-own", text="Looks sound", sequence=1)
    foreign_prompt_ref = ChatMessageRef(
        role="user", message_id="prompt-foreign", text="unrelated question", sequence=2
    )
    foreign_answer_ref = ChatMessageRef(
        role="assistant", message_id="assistant-foreign", text="unrelated answer", sequence=3
    )

    def _snapshot_with_refs(refs, *, assistant_text, assistant_id, generating=False, complete=False):
        signals = set()
        if generating:
            signals.add("stop-control")
        if complete:
            signals.add("completion-control")
            signals.add("more-actions-menu")
        user_refs = [r for r in refs if r.role == "user"]
        return ChatSnapshot(
            url="https://chatgpt.com/g/g-p-project/c/conversation-1",
            composer_present=True,
            composer_editable=True,
            user_count=len(user_refs),
            assistant_count=sum(1 for r in refs if r.role == "assistant"),
            latest_assistant_id=assistant_id,
            latest_user_text=user_refs[-1].text if user_refs else None,
            latest_assistant_text=assistant_text,
            dom_signals=frozenset(signals),
            error_present=False,
            latest_user_id=user_refs[-1].message_id if user_refs else None,
            generating=generating,
            message_refs=tuple(refs),
        )

    def _snapshots_gen():
        yield snap()  # baseline
        yield _snapshot_with_refs([own_prompt_ref], assistant_text=None, assistant_id=None)
        yield _snapshot_with_refs([own_prompt_ref], assistant_text=None, assistant_id=None)
        yield _snapshot_with_refs(
            [own_prompt_ref, own_answer_ref],
            assistant_text="Looks sound",
            assistant_id="assistant-own",
            generating=True,
        )
        # A foreign turn has now landed in the same conversation and become
        # conversation-global-latest -- the raw snapshot's own
        # latest_assistant_id/_text report the FOREIGN answer, exactly what
        # a human posting into the same tab (or a later gateway request)
        # would produce. The resolver must still return this request's own
        # answer, not this raw global-latest value.
        while True:
            yield _snapshot_with_refs(
                [own_prompt_ref, own_answer_ref, foreign_prompt_ref, foreign_answer_ref],
                assistant_text="unrelated answer",
                assistant_id="assistant-foreign",
                complete=True,
            )

    chat._snapshots = _snapshots_gen()
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review AU01"), lambda _: None)
    result = await turn.run()
    assert result.final_summary == "Looks sound"
    assert turn._response_message_id == "assistant-own"


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
async def test_stale_dom_response_conflict_refreshes_without_resubmitting() -> None:
    """A renderer bump must recover the original turn, not fail it.

    The first terminal-looking snapshot exposes a provisional assistant id;
    refreshing the same retained conversation exposes the final id.  The
    gateway must perform that read-only recovery exactly once and complete the
    original request with one provider submission.
    """
    chat = _Chat()
    final_snapshot = snap(
        users=1,
        assistants=1,
        user="Review AU01",
        assistant="final response",
        assistant_id="assistant-final",
        complete=True,
    )
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01", generating=True),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="partial",
                assistant_id="assistant-provisional",
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="final response",
                assistant_id="assistant-final",
                complete=True,
            ),
        ]
        + [final_snapshot] * 20
    )
    refresh_calls = 0

    async def refresh_same_conversation() -> bool:
        nonlocal refresh_calls
        refresh_calls += 1
        return True

    chat._refresh_for_reconciliation = refresh_same_conversation
    turn = GptAutoTurn(
        chat,
        SessionPrompt(turn_id="turn-stale-dom", body="Review AU01"),
        lambda _observation: None,
    )

    result = await turn.run()

    assert result.final_summary == "final response"
    assert chat.runtime.bridge.submit_calls == 1
    assert refresh_calls == 1
    assert turn._response_message_id == "assistant-final"


@pytest.mark.asyncio
async def test_terminal_verification_conflict_uses_same_refresh_path() -> None:
    """The independent verification read must not bypass identity recovery."""
    chat = _Chat()
    final_snapshot = snap(
        users=1,
        assistants=1,
        user="Review AU01",
        assistant="final response",
        assistant_id="assistant-final",
        complete=True,
    )
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01", generating=True),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="partial",
                assistant_id="assistant-candidate",
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="final response",
                assistant_id="assistant-candidate",
                complete=True,
            ),
            # The independent verification read sees a different DOM id but
            # identical text; this must trigger the same bounded refresh.
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="final response",
                assistant_id="assistant-final",
                complete=True,
            ),
        ]
        + [final_snapshot] * 20
    )
    refresh_calls = 0

    async def refresh_same_conversation() -> bool:
        nonlocal refresh_calls
        refresh_calls += 1
        return True

    chat._refresh_for_reconciliation = refresh_same_conversation
    turn = GptAutoTurn(
        chat,
        SessionPrompt(turn_id="turn-verification-conflict", body="Review AU01"),
        lambda _observation: None,
    )

    result = await turn.run()

    assert result.final_summary == "final response"
    assert chat.runtime.bridge.submit_calls == 1
    assert refresh_calls == 1
    assert turn._response_message_id == "assistant-final"


@pytest.mark.asyncio
async def test_turn_accepts_structural_dom_prompt_when_visible_text_loses_hr() -> None:
    """A DOM <hr> may remove exactly three source characters from visible text.

    The structural correlation field restores the source representation for
    submission proof while leaving the visible text projection unchanged.
    """
    chat = _Chat()
    source = "before\n---\nafter"
    visible = "before\nafter"
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user=visible, user_correlation=source, structural_hr_count=1),
            snap(users=1, user=visible, user_correlation=source, structural_hr_count=1),
            snap(users=1, user=visible, user_correlation=source, structural_hr_count=1, generating=True),
            snap(users=1, assistants=1, user=visible, user_correlation=source, structural_hr_count=1, assistant="Looks"),
            snap(users=1, assistants=1, user=visible, user_correlation=source, structural_hr_count=1, assistant="Looks"),
            snap(users=1, assistants=1, user=visible, user_correlation=source, structural_hr_count=1, assistant="Looks sound", complete=True),
            snap(users=1, assistants=1, user=visible, user_correlation=source, structural_hr_count=1, assistant="Looks sound", complete=True),
            snap(users=1, assistants=1, user=visible, user_correlation=source, structural_hr_count=1, assistant="Looks sound", complete=True),
        ]
    )

    result = await GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-structural", body=source), lambda _obs: None
    ).run()

    assert result.final_summary == "Looks sound"


@pytest.mark.asyncio
async def test_response_progress_activity_emits_repeatedly_not_just_once():
    """GP07 regression guard: a rewiring mistake made during the
    _await_response engine migration suppressed the response-progress
    ACTIVITY emission after the first occurrence. The gateway's own
    watchdog activity lease depends on these arriving throughout the turn,
    not just once at the start -- streaming text growing over several
    polls must produce more than one response-progress observation."""
    chat = _Chat()
    observations = []
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01"),
            snap(users=1, assistants=1, user="Review AU01", assistant="Looks"),
            snap(users=1, assistants=1, user="Review AU01", assistant="Looks so"),
            snap(users=1, assistants=1, user="Review AU01", assistant="Looks sound"),
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
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-progress", body="Review AU01"), observations.append
    )
    result = await turn.run()
    assert result.stop_reason == "end-turn"
    progress_observations = [
        obs
        for obs in observations
        if obs.attributes.get("model_activity") == "response-progress"
    ]
    assert len(progress_observations) >= 2


@pytest.mark.asyncio
async def test_tool_app_activity_emits_progress_when_response_text_is_unchanged():
    """Connector/tool affordances are real current-turn activity.

    ChatGPT can spend a long interval showing ``Called tool`` or ``Talked to
    App`` while the assistant text and busy widget remain unchanged. Those
    bounded label-count edges must renew both the provider observation lease
    and the internal response-progress clock.
    """
    chat = _Chat()
    observations = []
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01", generating=True),
            snap(users=1, assistants=1, user="Review AU01", assistant="Working"),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Working",
                tool_activity_counts=(("called-tool", 1),),
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Working",
                tool_activity_counts=(("called-tool", 1), ("talked-to-app", 1)),
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Done",
                complete=True,
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Done",
                complete=True,
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Done",
                complete=True,
            ),
        ]
    )
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-tool-progress", body="Review AU01"), observations.append
    )

    result = await turn.run()

    assert result.stop_reason == "end-turn"
    tool_progress = [
        obs
        for obs in observations
        if obs.attributes.get("model_activity") == "tool-progress"
    ]
    assert len(tool_progress) >= 2


@pytest.mark.asyncio
async def test_tool_app_activity_emits_before_assistant_message_materializes():
    """Streaming connector rows renew activity before an assistant node exists.

    ChatGPT can expose ``Talked to App``/``Read resource`` rows in the current
    ``.agent-turn`` while ``assistantCount`` and assistant text are still zero.
    The CDP snapshot fallback must preserve those counts so the turn emits
    provider progress instead of waiting for the final assistant node.
    """
    chat = _Chat()
    observations = []
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01", generating=True),
            snap(
                users=1,
                user="Review AU01",
                generating=True,
                tool_activity_counts=(("talked-to-app", 1),),
            ),
            snap(
                users=1,
                user="Review AU01",
                generating=True,
                tool_activity_counts=(("talked-to-app", 1), ("read-resource", 1)),
            ),
            snap(users=1, assistants=1, user="Review AU01", assistant="Done", complete=True),
            snap(users=1, assistants=1, user="Review AU01", assistant="Done", complete=True),
            snap(users=1, assistants=1, user="Review AU01", assistant="Done", complete=True),
        ]
    )
    turn = GptAutoTurn(
        chat,
        SessionPrompt(turn_id="turn-tool-before-assistant", body="Review AU01"),
        observations.append,
    )

    result = await turn.run()

    assert result.stop_reason == "end-turn"
    tool_progress = [
        obs
        for obs in observations
        if obs.attributes.get("model_activity") == "tool-progress"
    ]
    assert len(tool_progress) >= 2


@pytest.mark.asyncio
async def test_static_tool_activity_renews_with_bounded_heartbeat():
    """A visible tool row need not change its count every poll.

    The browser can display one ``Searching the web``/``Read resource`` row
    for minutes while that operation is still executing.  The gateway must
    receive periodic activity rather than treating the unchanged row as
    silence.  The production cadence is five seconds; this test forces it to
    zero so the deterministic fixture can exercise multiple heartbeats.
    """
    chat = _Chat()
    observations = []
    chat._snapshots = iter(
        [
            snap(),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01"),
            snap(users=1, user="Review AU01", generating=True),
            snap(users=1, assistants=1, user="Review AU01", assistant="Working"),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Working",
                tool_activity_counts=(("searching-web", 1),),
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Working",
                tool_activity_counts=(("searching-web", 1),),
            ),
            snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="Working",
                tool_activity_counts=(("searching-web", 1),),
            ),
            snap(users=1, assistants=1, user="Review AU01", assistant="Done", complete=True),
            snap(users=1, assistants=1, user="Review AU01", assistant="Done", complete=True),
            snap(users=1, assistants=1, user="Review AU01", assistant="Done", complete=True),
        ]
    )
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-tool-heartbeat", body="Review AU01"), observations.append
    )
    turn._TOOL_ACTIVITY_HEARTBEAT_INTERVAL_SECONDS = 0.0

    result = await turn.run()

    assert result.stop_reason == "end-turn"
    tool_progress = [
        obs
        for obs in observations
        if obs.attributes.get("model_activity") == "tool-progress"
    ]
    assert len(tool_progress) >= 2


@pytest.mark.asyncio
async def test_submission_proof_resolves_ambiguous_not_hung_when_text_never_exactly_matches():
    """GP07: a real bug found live -- a new user message can appear with a
    length matching the sent prompt but content that never satisfies strict
    equality (code-block rendering artifacts). The activity-aware engine
    must not hang forever chasing an exact match that may never arrive; it
    must resolve to ambiguous (None -> EXT-GPTAUTO-003, submission-ambiguous
    -- never a silent success, never an infinite wait) once genuinely
    stalled, while still recognizing each new (edge-triggered) mismatched
    message as real PROGRESS along the way."""
    chat = _Chat()
    chat.runtime.config.turn.submission_proof_progress_lease_seconds = 0.05
    chat.runtime.config.turn.submission_proof_absolute_ceiling_seconds = 0.3

    def _never_matching_snapshots():
        yield snap()
        counter = 0
        while True:
            counter += 1
            yield snap(users=1, user=f"Review AU01 (rendered variant {counter})")

    chat._snapshots = _never_matching_snapshots()
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-never-matches", body="Review AU01"), lambda _: None
    )
    with pytest.raises(AudiaGenticError) as error:
        await turn.run()
    assert error.value.details.get("submission-ambiguous") is True
    assert turn.state is not TurnState.COMPLETE


@pytest.mark.asyncio
async def test_submission_proof_finder_fallback_receives_raw_prompt_text():
    """GP25 regression: _await_submission_proof()'s duplicate-tab fallback
    (chat.find_prompt_snapshot) must be called with the raw prompt string,
    not a PromptFingerprint object -- a real live bug where a leftover
    `expected` reference (removed when GP25 migrated off the old _normal()
    variable) caused a bare NameError in production the first time this
    fallback branch actually ran, uncaught by every other test because
    none of them give the fake chat a find_prompt_snapshot attribute at
    all (so the fallback branch was never exercised)."""
    chat = _Chat()
    chat.runtime.config.turn.submission_proof_progress_lease_seconds = 0.05
    chat.runtime.config.turn.submission_proof_absolute_ceiling_seconds = 0.3

    def _never_matching_snapshots():
        yield snap()
        counter = 0
        while True:
            counter += 1
            yield snap(users=1, user=f"Review AU01 (rendered variant {counter})")

    chat._snapshots = _never_matching_snapshots()

    calls: list[tuple[object, object]] = []

    async def find_prompt_snapshot(baseline, expected_text):
        calls.append((baseline, expected_text))
        return None

    chat.find_prompt_snapshot = find_prompt_snapshot
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-finder-fallback", body="Review AU01"), lambda _: None
    )
    with pytest.raises(AudiaGenticError):
        await turn.run()
    assert calls, "find_prompt_snapshot fallback was never invoked"
    assert all(isinstance(expected_text, str) for _, expected_text in calls)
    assert all(expected_text == "Review AU01" for _, expected_text in calls)


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
async def test_response_completion_logs_the_deciding_observation_evidence(caplog):
    """GP46: two live incidents persisted truncated/mid-stream output with no
    trace of which indicators the tracker accepted as terminal. The tracker's
    state transitions and the accepting evidence must now be logged (evidence
    predicate names, dom-signal names, and text LENGTH -- never response
    content) so a recurrence is diagnosable from the process log."""
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
                assistant="Looks sound",
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
        chat, SessionPrompt(turn_id="turn-trace-evidence", body="Review AU01"), lambda _: None
    )
    with caplog.at_level("INFO", logger="audiagentic.components.providers.adapters.gpt_auto.turn"):
        result = await turn.run()
    assert result.final_summary == "Looks sound"

    transition_records = [
        r for r in caplog.records if "gpt-auto observation transition" in r.getMessage()
    ]
    assert transition_records, "expected at least one observation-transition log line"
    assert all(getattr(r, "turn-id", None) == "turn-trace-evidence" for r in transition_records)

    verified_records = [
        r
        for r in caplog.records
        if "gpt-auto response completion verification result" in r.getMessage()
    ]
    assert verified_records, "expected a verification-result log line"
    assert "True" in verified_records[-1].getMessage()
    assert "candidate_text_len=11" in verified_records[-1].getMessage()

    # No log line in this path may ever contain the actual response text.
    for record in caplog.records:
        assert "Looks sound" not in record.getMessage()


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
async def test_response_wait_stalls_correctly_despite_flapping_soft_liveness_widget():
    """GP07: a real latent hole found while rewiring _await_response --
    response-active's any-of previously let stop-control/streaming/thinking
    widget transitions ALONE reset last_activity_at, so a widget flapping
    forever (no real text ever appearing) could indefinitely postpone the
    stall timeout. Widget transitions are SOFT_LIVENESS now (bounded grace
    only); with no real content ever arriving, this must still resolve to
    a stall/failure, not hang."""
    chat = _Chat()
    chat.runtime.config.turn.response_start_timeout_seconds = 0.05
    chat.runtime.config.turn.response_stall_timeout_seconds = 0.05
    chat.runtime.config.turn.response_timeout_seconds = 0.3

    def _flapping_stop_control_no_text_ever():
        toggle = False
        while True:
            toggle = not toggle
            yield snap(users=1, assistants=1, user="Review AU01", assistant="", generating=toggle)

    chat._snapshots = _flapping_stop_control_no_text_ever()
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-flapping-widget", body="Review AU01"), lambda _: None
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
    chat._snapshots = iter(
        [snap(), snap(users=1, user="Review SH10"), snap(users=1, user="Review SH10"), failed]
    )
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="Review SH10"), lambda _: None)

    with pytest.raises(Exception, match="provider failure policy matched"):
        await turn.run()

    assert transitions.count((ChatState.BUSY, ChatState.FAILED)) == 1


def test_prompt_identity_preserves_case_and_indentation_presence():
    """GP43 (2026-08-17): exact interior-whitespace RUN LENGTH is no longer
    compared -- ChatGPT's renderer proved unable to preserve it reliably
    (a run of 9 plain spaces was observed collapsed to a single \xa0).
    Case and indentation DEPTH (present vs absent) remain significant."""
    from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import (
        normalize_prompt_text,
    )

    assert normalize_prompt_text("Return Foo") != normalize_prompt_text("return foo")
    assert normalize_prompt_text("x  y") == normalize_prompt_text("x y")
    assert normalize_prompt_text("if ok:\n    run()") != normalize_prompt_text("if ok:\nrun()")
    assert normalize_prompt_text("line\r\n") == "line"


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


def test_response_stall_timeout_disabled_means_unbounded_across_every_phase():
    """GP15: response-stall-timeout-seconds=0 is documented as "disabled",
    but only progress_lease_seconds/absolute_ceiling_seconds actually
    honored that -- soft_grace_cap_seconds, candidate_max_verification_
    window_seconds, and suspect_grace_seconds silently fell back to a
    fixed 60s. Proven live 2026-08-16: a genuinely-in-progress consultation
    (no assistant text yet, stop-control persistently visible but never
    toggling, so SOFT_LIVENESS was never granted -- edge-triggered) was
    falsely marked failed via response-stall-timeout at ~195s even though
    the config said stall detection was disabled. Every disable-sensitive
    timing property must agree, or the "disabled" contract is a lie for
    whichever path a caller's actual DOM behavior happens to route through."""
    from audiagentic.components.providers.adapters.gpt_auto.turn import (
        _ResponseCompletionPolicy,
    )

    turn_config = SimpleNamespace(
        response_start_timeout_seconds=120.0,
        response_stall_timeout_seconds=0,
        response_timeout_seconds=3600.0,
        response_stability_seconds=6.0,
    )
    policy = _ResponseCompletionPolicy(turn_config)
    assert policy.progress_lease_seconds == float("inf")
    assert policy.soft_grace_cap_seconds == float("inf")
    assert policy.candidate_max_verification_window_seconds == float("inf")
    assert policy.suspect_grace_seconds == float("inf")
    # response_start_timeout_seconds and response_timeout_seconds are their
    # own independent, legitimately-finite bounds -- disabling stall
    # detection must not implicitly disable them too.
    assert policy.start_bound_seconds == 120.0
    assert policy.absolute_ceiling_seconds == 3600.0


@pytest.mark.asyncio
async def test_turn_does_not_complete_on_more_actions_menu_alone_without_completion_control():
    """GP17/GP32: completion-control's corroborating partner (message-
    finalized until GP32, 2026-08-17, when its underlying DOM marker was
    removed by ChatGPT and more-actions-menu replaced it) was proven live
    to fire on a genuinely incomplete response while completion-control
    was absent -- the exact scenario that produced real truncated
    "completed" results on 2026-08-16. With only the corroborating signal
    present (no completion-control, text never growing), the turn must
    NOT complete -- it must time out instead, never falsely report success
    on a short, unfinished answer."""
    chat = _Chat()
    chat.runtime.config.turn.response_start_timeout_seconds = 0.05
    chat.runtime.config.turn.response_stall_timeout_seconds = 0.05
    chat.runtime.config.turn.response_timeout_seconds = 0.3

    def _short_stuck_response_more_actions_menu_only():
        while True:
            yield snap(
                users=1,
                assistants=1,
                user="Review AU01",
                assistant="I would",
                extra_signals=["more-actions-menu"],
            )

    chat._snapshots = _short_stuck_response_more_actions_menu_only()
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-more-actions-menu-alone", body="Review AU01"), lambda _: None
    )
    with pytest.raises(AudiaGenticError):
        await turn.run()


@pytest.mark.asyncio
async def test_await_composer_settled_returns_immediately_when_already_settled():
    """GP11: an already-settled baseline (not generating, composer editable)
    must not consume any extra snapshots or wait -- the fast path for the
    overwhelmingly common case."""
    chat = _Chat()
    chat.runtime.config.turn.submission_timeout_seconds = 1.0
    chat.runtime.config.turn.poll_interval_seconds = 0.01
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="hi"), lambda _: None)
    already_settled = snap(generating=False, composer_editable=True)
    result = await turn._await_composer_settled(already_settled)
    assert result is already_settled


@pytest.mark.asyncio
async def test_await_composer_settled_polls_until_generating_clears():
    """GP11: a baseline caught while the previous turn is still generating
    (or the composer isn't yet editable again) must be re-observed until it
    settles, within the bounded budget, rather than submitting into a
    composer that isn't ready yet."""
    chat = _Chat()
    chat.runtime.config.turn.submission_timeout_seconds = 1.0
    chat.runtime.config.turn.poll_interval_seconds = 0.01
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="hi"), lambda _: None)

    def _settles_after_two_polls():
        yield snap(generating=True)
        yield snap(generating=True)
        yield snap(generating=False)

    chat._snapshots = _settles_after_two_polls()
    start = snap(generating=True)
    result = await turn._await_composer_settled(start)
    assert result.generating is False


@pytest.mark.asyncio
async def test_await_composer_settled_gives_up_after_bounded_budget_without_hanging():
    """A composer that never settles must not hang the turn forever -- the
    bounded budget expires and the (still unsettled) snapshot is returned
    so the caller can proceed anyway; submit()'s own bounded retry (GP11)
    is the remaining safety net, not an indefinite wait here."""
    chat = _Chat()
    chat.runtime.config.turn.submission_timeout_seconds = 0.05
    chat.runtime.config.turn.poll_interval_seconds = 0.01
    turn = GptAutoTurn(chat, SessionPrompt(turn_id="turn-1", body="hi"), lambda _: None)

    def _never_settles():
        while True:
            yield snap(generating=True)

    chat._snapshots = _never_settles()
    start = snap(generating=True)
    result = await asyncio.wait_for(turn._await_composer_settled(start), timeout=2.0)
    assert result.generating is True
    assert turn.state is not TurnState.COMPLETE


@pytest.mark.asyncio
async def test_submission_proof_does_not_starve_while_assistant_text_keeps_growing():
    """GP19: a real live incident where the submitted prompt's text never
    matched (Markdown-stripped rendering, most likely) but the assistant
    was genuinely, continuously writing a real answer (generating=True,
    growing text) the whole time -- the OLD code granted PROGRESS/
    SOFT_LIVENESS only on the one poll where the new user message first
    appeared, then starved to EvidenceCapability.NONE forever, timing out
    despite unambiguous ongoing activity. Growing assistant text must now
    keep resetting the progress lease, so the wait runs close to the full
    absolute ceiling (consuming many polls) instead of stalling out almost
    immediately after the one-time initial match failure."""
    chat = _Chat()
    # _await_submission_proof() polls on a hardcoded 0.2s cadence (not
    # poll_interval_seconds) -- the lease must comfortably exceed that or
    # every poll starts the observation stalled before it can even repeat.
    chat.runtime.config.turn.submission_proof_progress_lease_seconds = 1.0
    chat.runtime.config.turn.submission_proof_absolute_ceiling_seconds = 2.0

    poll_count = 0

    def _new_message_never_matches_but_assistant_keeps_growing():
        nonlocal poll_count
        # First poll: a new user message appears, but its text does not
        # match the expected prompt (simulates Markdown-stripped rendering).
        poll_count += 1
        yield snap(users=1, user="totally different rendered text", generating=True)
        # Every subsequent poll: prompt text still never matches, but the
        # assistant's own text keeps growing -- real, continuing activity.
        counter = 0
        while True:
            counter += 1
            poll_count += 1
            yield snap(
                users=1,
                user="totally different rendered text",
                assistants=1,
                assistant=f"partial answer {counter}",
                generating=True,
            )

    chat._snapshots = _new_message_never_matches_but_assistant_keeps_growing()
    turn = GptAutoTurn(
        chat, SessionPrompt(turn_id="turn-gp19", body="Review AU01"), lambda _: None
    )
    baseline = snap()
    result = await asyncio.wait_for(turn._await_submission_proof(baseline), timeout=5.0)
    assert result is None  # text truly never matched -- correctly stays ambiguous, not a false success
    # With the fix, growing assistant text keeps the lease alive for close
    # to the full absolute ceiling rather than starving after ~1-2 polls.
    assert poll_count >= 10, (
        f"only consumed {poll_count} polls before giving up -- growing assistant "
        "text should have kept the observation alive far longer than this"
    )
