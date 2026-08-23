from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto import runtime as runtime_module
from audiagentic.components.providers.adapters.gpt_auto.cdp.bridge import BridgeEvent
from audiagentic.components.providers.adapters.gpt_auto.chat import (
    ChatState,
    PersistentChat,
    _unresolved_prompt_match,
    _unresolved_prompt_match_diagnostics,
)
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime import (
    GptAutoProviderRuntime,
    ProviderState,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot
from audiagentic.components.providers.adapters.gpt_auto.window_anchor import (
    gateway_dashboard_anchor_url,
    gateway_dashboard_url,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_greenfield_config_urls import valid_config


def test_unresolved_recovery_can_match_prompt_text_without_provider_message_id() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    chat = PersistentChat(
        ag_session_id="session-text-fallback",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.mark_submission_unresolved("Review the current recovery state")
    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=1,
        latest_assistant_id="assistant-1",
        latest_user_text="Review the current recovery state",
        latest_assistant_text="done",
        dom_signals=frozenset({"completion-control"}),
        error_present=False,
        latest_user_id=None,
        user_message_texts=("Review the current recovery state",),
    )

    assert _unresolved_prompt_match(chat, snapshot) == f"text:{chat.unresolved_prompt_text_digest}"

    ambiguous = replace(
        snapshot,
        user_message_texts=(snapshot.latest_user_text, snapshot.latest_user_text),
    )
    assert _unresolved_prompt_match(chat, ambiguous) is None


def test_unresolved_prompt_diagnostics_distinguish_id_mismatch_and_digest_fallback() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    chat = PersistentChat(
        ag_session_id="session-diagnostics",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        resume_provider_metadata={
            "prompt-message-id": "missing-id",
            "prompt-text-digest": "f" * 64,
            "unresolved-turn-pending": True,
        },
    )
    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text="different prompt",
        latest_assistant_text=None,
        dom_signals=frozenset(),
        error_present=False,
        user_message_texts=("different prompt",),
        latest_user_id="other-id",
    )

    match, reason, details = _unresolved_prompt_match_diagnostics(chat, snapshot)

    assert match is None
    assert reason == "prompt-text-digest-not-found"
    assert details["expected-prompt-id"] == "missing-id"
    assert details["observed-latest-user-id"] == "other-id"
    assert details["observed-user-count"] == 1


def test_completed_resume_message_ids_do_not_imply_unresolved_turn() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    chat = PersistentChat(
        ag_session_id="session-completed-resume",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        resume_provider_metadata={
            "prompt-message-id": "prompt-1",
            "assistant-message-id": "assistant-1",
        },
    )

    assert chat.unresolved_turn_pending is False
    assert chat.unresolved_metadata()["unresolved-turn-pending"] is False


@pytest.mark.asyncio
async def test_unresolved_checkpoint_persists_snapshot_counts() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    updates = []
    chat = PersistentChat(
        ag_session_id="session-checkpoint-counts",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        checkpoint_sink=updates.append,
    )
    baseline = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=True,
        composer_editable=True,
        user_count=3,
        assistant_count=2,
        latest_assistant_id="assistant-2",
        latest_user_text="prompt",
        latest_assistant_text="answer",
        dom_signals=frozenset(),
        error_present=False,
    )

    await chat.persist_unresolved_checkpoint(turn_id="turn-1", baseline=baseline)

    assert updates[-1]["unresolved-baseline-user-count"] == 3
    assert updates[-1]["unresolved-baseline-assistant-count"] == 2


def test_explicit_unresolved_marker_remains_authoritative() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    chat = PersistentChat(
        ag_session_id="session-pending-resume",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        resume_provider_metadata={
            "prompt-message-id": "prompt-1",
            "assistant-message-id": "assistant-1",
            "unresolved-turn-pending": True,
        },
    )

    assert chat.unresolved_turn_pending is True
    assert chat.unresolved_metadata()["unresolved-turn-pending"] is True


class _EventBridge:
    def __init__(self) -> None:
        self.events: asyncio.Queue[BridgeEvent] = asyncio.Queue()


@pytest.mark.asyncio
async def test_runtime_routes_only_terminal_page_events_to_page_loss() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    bridge = _EventBridge()
    runtime._bridge = bridge  # type: ignore[assignment]
    runtime.state = ProviderState.AVAILABLE
    chat = SimpleNamespace(page_handle="page-1", lost=[])

    async def page_lost(handle: str) -> None:
        chat.lost.append(handle)

    chat.page_lost = page_lost
    runtime._chats = {"session-1": chat}
    task = asyncio.create_task(runtime._route_events(bridge))  # type: ignore[arg-type]
    try:
        await bridge.events.put(BridgeEvent("target_changed", "page-1"))
        await bridge.events.put(BridgeEvent("page_lifecycle", "page-1"))
        await asyncio.sleep(0)
        assert chat.lost == []

        await bridge.events.put(BridgeEvent("page_closed", "page-1"))
        await asyncio.sleep(0)
        assert chat.lost == ["page-1"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class _Page:
    handle = "page-1"


class _GptBrowser:
    def __init__(self) -> None:
        self.closed: list[_Page] = []
        self.open_kwargs: list[dict] = []

    async def open_project_page(self, **kwargs):
        self.open_kwargs.append(kwargs)
        return {"page": _Page(), "projectUrl": "https://chatgpt.com/g/g-p-project/project"}

    async def close(self, page: _Page) -> None:
        self.closed.append(page)


class _OpenRuntime:
    def __init__(self) -> None:
        config = valid_config()
        config["browser"]["dedicated-window"] = False
        self.config = GptAutoConfig.from_dict(config)
        self.gpt_browser = _GptBrowser()
        self.anchor_page = _Page()
        self._owners: dict[str, str] = {}

    async def ensure_available(self) -> None:
        return None

    async def register_chat(self, _chat) -> None:
        return None

    async def dedicated_window_anchor_page(self):
        return self.anchor_page

    def unregister_chat(self, _chat) -> None:
        return None

    def claim_page(self, chat, page_handle: str) -> bool:
        owner = self._owners.get(page_handle)
        if owner and owner != chat.ag_session_id:
            return False
        self._owners[page_handle] = chat.ag_session_id
        return True


@pytest.mark.asyncio
async def test_fast_open_claims_page_before_ready_and_rejects_second_session() -> None:
    runtime = _OpenRuntime()
    first = PersistentChat(
        ag_session_id="session-a",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=runtime.config,
        binding_sink=lambda _update: None,
    )
    await first.open()
    assert first.page_handle == "page-1"

    second = PersistentChat(
        ag_session_id="session-b",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=runtime.config,
        binding_sink=lambda _update: None,
    )
    with pytest.raises(RuntimeError, match="already owned"):
        await second.open()
    assert len(runtime.gpt_browser.closed) == 1


@pytest.mark.asyncio
async def test_new_project_session_reuses_dashboard_anchor_window() -> None:
    """A new session is opened as a tab in the managed GPT window."""
    runtime = _OpenRuntime()
    config = valid_config()
    config["browser"]["dedicated-window"] = True
    runtime.config = GptAutoConfig.from_dict(config)

    chat = PersistentChat(
        ag_session_id="session-independent-window",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=runtime.config,
        binding_sink=lambda _update: None,
    )

    await chat.open()

    assert runtime.gpt_browser.open_kwargs == [
        {
            "project_name": "project",
            "project_url": "https://chatgpt.com/g/g-p-project/project",
            "anchor_page": runtime.anchor_page,
            "navigation_timeout": runtime.config.chat.navigation_timeout_seconds,
            "ready_timeout": runtime.config.chat.ready_timeout_seconds,
        }
    ]


@pytest.mark.asyncio
async def test_runtime_waits_for_cdp_endpoint_after_browser_launch(monkeypatch) -> None:
    attempts: list[str] = []

    class _Bridge:
        def __init__(self, _config) -> None:
            attempts.append("new")

        async def start(self, **_kwargs) -> None:
            if attempts.count("new") < 3:
                raise OSError("connection refused")

        async def stop(self) -> None:
            attempts.append("stop")

    monkeypatch.setattr(runtime_module, "PythonCdpBridge", _Bridge)
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    bridge = await runtime._connect_bridge()
    assert isinstance(bridge, _Bridge)
    assert attempts.count("new") == 3
    assert attempts.count("stop") == 2


@pytest.mark.asyncio
async def test_runtime_shutdown_is_legal_during_connection_start() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.CONNECTING
    await runtime.shutdown()
    assert runtime.state is ProviderState.STOPPED


@pytest.mark.asyncio
async def test_chat_recovery_retains_page_after_recoverable_turn_failure() -> None:
    config = GptAutoConfig.from_dict(valid_config())

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 0,
                "assistantCount": 0,
                "domSignals": {},
                "errorPresent": False,
            }

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=SimpleNamespace(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-recover",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.FAILED

    retained = await chat.retain_after_turn_failure(
        AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="prompt proof was ambiguous",
            details={"submission-ambiguous": True},
        )
    )

    assert retained is True
    assert chat.state.value == "ready"
    assert chat.page_handle == "page-1"


@pytest.mark.asyncio
async def test_unknown_submitted_turn_cannot_promote_idle_composer_to_ready() -> None:
    config = GptAutoConfig.from_dict(valid_config())

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": "https://chatgpt.com/g/g-p-project/c/conversation-1",
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 1,
                "assistantCount": 1,
                "latestAssistantId": "assistant-old",
                "latestAssistantText": "older response",
                "domSignals": {},
                "errorPresent": False,
            }

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=SimpleNamespace(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-unresolved",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.RECOVERING
    chat.mark_submission_unresolved()

    retained = await chat.retain_after_turn_failure(
        AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="submission proof was ambiguous",
        )
    )

    assert retained is True
    assert chat.state is ChatState.RECOVERING
    with pytest.raises(AudiaGenticError, match="could not reconcile the previous turn") as error:
        await chat.ensure_ready()
    assert error.value.code == "EXT-GPTAUTO-004"
    assert error.value.details["failure-reason"] == "unresolved-turn-not-reconciled"
    assert error.value.details["recovery-reason"] == "prompt-correlation-evidence-missing"


@pytest.mark.asyncio
async def test_unresolved_recovery_reports_missing_completion_evidence() -> None:
    config = GptAutoConfig.from_dict(valid_config())

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": "https://chatgpt.com/g/g-p-project/c/conversation-1",
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 1,
                "assistantCount": 1,
                "latestAssistantId": "assistant-new",
                "latestAssistantText": "new response",
                "latestUserText": "the submitted prompt",
                "userMessageTexts": ["the submitted prompt"],
                "domSignals": {},
                "errorPresent": False,
            }

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=SimpleNamespace(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-missing-completion",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.RECOVERING
    chat.mark_submission_unresolved("the submitted prompt")

    with pytest.raises(AudiaGenticError) as error:
        await chat.ensure_ready()

    assert error.value.code == "EXT-GPTAUTO-004"
    assert error.value.details["recovery-reason"] == "completion-evidence-missing"
    assert error.value.details["recovery-details"]["required-signal"] == (
        "completion-control+more-actions-menu"
        "-or-canvas-edit-control+canvas-open-editor-control+not-generating"
    )


@pytest.mark.asyncio
async def test_unresolved_recovery_reconciles_despite_stuck_generating_signal() -> None:
    """Live-reproduced 2026-08-16 (GP05 L4 scenario): reconciliation of an
    unresolved turn must not be permanently blocked by a stuck
    generating=True/stop-control signal once real completion evidence
    (completion-control here) corroborates that the response is done --
    matches the composer-editable=True + stop-control-stuck combination
    observed live, which is itself evidence the button state is stale."""
    config = GptAutoConfig.from_dict(valid_config())

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": "https://chatgpt.com/g/g-p-project/c/conversation-1",
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 1,
                "assistantCount": 1,
                "latestAssistantId": "assistant-new",
                "latestAssistantText": "new response",
                "latestUserText": "the submitted prompt",
                "userMessageTexts": ["the submitted prompt"],
                "domSignals": {
                    "completion-control": True,
                    "more-actions-menu": True,
                    "stop-control": True,
                },
                "generating": True,
                "errorPresent": False,
            }

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=SimpleNamespace(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-stuck-generating",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.RECOVERING
    chat.mark_submission_unresolved("the submitted prompt")

    # First reconciliation attempt: correlation evidence matches but a
    # second stable observation is required before clearing.
    with pytest.raises(AudiaGenticError) as first_error:
        await chat.ensure_ready()
    assert first_error.value.details["recovery-reason"] == "awaiting-second-stable-observation"

    # GP18 code review: a matching fingerprint alone is not enough -- real
    # time must also pass (response_stability_seconds), so a caller
    # retrying immediately can't rush past the stability window. Simulate
    # that real time elapsed between the two observations.
    chat._unresolved_match_fingerprint_at -= config.turn.response_stability_seconds + 1

    # Second identical observation, after the stability window: reconciles
    # successfully despite the stuck generating=True/stop-control the
    # whole time.
    await chat.ensure_ready()
    assert chat.state is ChatState.READY
    assert chat.unresolved_turn_pending is False


@pytest.mark.asyncio
async def test_chat_readiness_requires_two_stable_quiescent_snapshots() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    values = iter(
        [
            {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "generating": True,
                "userCount": 1,
                "assistantCount": 0,
                "domSignals": {"stop-control": True},
            },
            {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "generating": False,
                "userCount": 1,
                "assistantCount": 1,
                "latestAssistantId": "a1",
                "latestAssistantText": "done",
                "domSignals": {},
            },
            {
                "url": "https://chatgpt.com/g/g-p-project/project",
                "composerPresent": True,
                "composerEditable": True,
                "generating": False,
                "userCount": 1,
                "assistantCount": 1,
                "latestAssistantId": "a1",
                "latestAssistantText": "done",
                "domSignals": {},
            },
        ]
    )

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return next(values)

    runtime = SimpleNamespace(gpt_browser=_Browser(), bridge=SimpleNamespace())
    chat = PersistentChat(
        ag_session_id="session-quiescent",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.RECOVERING

    result = await chat.wait_quiescent(allow_recovering=True)

    assert result.latest_assistant_text == "done"


@pytest.mark.asyncio
async def test_chat_close_retains_tab_by_default_for_gateway_resume() -> None:
    config = GptAutoConfig.from_dict(valid_config())

    class _Bridge:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call(self, method: str, params: dict) -> None:
            self.calls.append((method, params))

    bridge = _Bridge()
    runtime = SimpleNamespace(
        bridge=bridge,
        config=config,
        release_page=lambda _chat, _handle: None,
        unregister_chat=lambda _chat: None,
    )
    chat = PersistentChat(
        ag_session_id="session-retain",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.READY

    await chat.close()

    assert chat.state is ChatState.CLOSED
    assert chat.page_handle is None
    assert bridge.calls == []


@pytest.mark.asyncio
async def test_chat_close_can_opt_in_to_closing_tab() -> None:
    value = valid_config()
    value["browser"]["close-tabs-on-session-close"] = True
    config = GptAutoConfig.from_dict(value)

    class _Bridge:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call(self, method: str, params: dict) -> None:
            self.calls.append((method, params))

    bridge = _Bridge()
    runtime = SimpleNamespace(
        bridge=bridge,
        config=config,
        release_page=lambda _chat, _handle: None,
        unregister_chat=lambda _chat: None,
    )
    chat = PersistentChat(
        ag_session_id="session-close-tab",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.READY

    await chat.close()

    assert bridge.calls == [("close_page", {"pageHandle": "page-1"})]


@pytest.mark.asyncio
async def test_recovery_invalidates_handles_globally_but_reconciles_active_chat_only(monkeypatch) -> None:
    """GP05: a shared bridge fault invalidates every chat's page handle
    (bridge_replaced() for all), but eager reconcile() is reserved for a
    chat with an in-flight turn. An idle chat must NOT be driven through
    reconcile() here -- it reconciles lazily on its own next ensure_ready()
    instead, so one project's bridge fault does not stall an unrelated
    idle project sharing the runtime."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    old = SimpleNamespace(stop=lambda: _done())
    replacement = SimpleNamespace(call=lambda method: _pages() if method == "list_pages" else None)
    runtime._bridge = old
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_anchor = "page-1"
    runtime._page_owners = {"page-1": "session-a", "page-2": "session-b"}

    active_chat = SimpleNamespace(replaced=0, reconciled=None, active_turn_id="turn-1")
    idle_chat = SimpleNamespace(replaced=0, reconciled=None, active_turn_id=None)

    def make_bridge_replaced(chat):
        def bridge_replaced() -> None:
            chat.replaced += 1

        return bridge_replaced

    def make_reconcile(chat):
        async def reconcile(pages) -> None:
            chat.reconciled = pages

        return reconcile

    active_chat.bridge_replaced = make_bridge_replaced(active_chat)
    active_chat.reconcile = make_reconcile(active_chat)
    idle_chat.bridge_replaced = make_bridge_replaced(idle_chat)
    idle_chat.reconcile = make_reconcile(idle_chat)
    runtime._chats = {"session-a": active_chat, "session-b": idle_chat}

    async def ensure_available() -> None:
        runtime._bridge = replacement
        runtime._gpt_browser = SimpleNamespace()
        runtime.state = ProviderState.AVAILABLE

    monkeypatch.setattr(runtime, "ensure_available", ensure_available)
    await runtime.recover()

    # Both chats' bridge-local handles are invalidated -- the shared socket
    # really did die for everyone.
    assert active_chat.replaced == 1
    assert idle_chat.replaced == 1
    # Only the actively in-flight chat pays the eager reconciliation cost.
    assert active_chat.reconciled == [{"pageHandle": "page-1", "targetId": "new-target"}]
    assert idle_chat.reconciled is None
    assert runtime._page_owners == {}
    assert runtime._dedicated_window_anchor is None


@pytest.mark.asyncio
async def test_resume_open_recovers_via_retained_tab_when_chat_url_missing() -> None:
    """Missing chat-url must not block resume when a retained tab is found."""
    config = GptAutoConfig.from_dict(valid_config())
    retained_page = {
        "pageHandle": "retained-handle",
        "targetId": "retained-target",
        "url": "https://chatgpt.com/g/g-p-project/c/provider-session",
    }

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": retained_page["url"],
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 1,
                "assistantCount": 1,
                "domSignals": {},
                "errorPresent": False,
            }

    async def find_conversation_page(_provider_session_id, *, preferred_target_id=None):
        return retained_page

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [retained_page]

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=_Bridge(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
        find_conversation_page=find_conversation_page,
        register_chat=lambda _chat: _done(),
        claim_conversation=lambda _chat, _provider_session_id: True,
        ensure_available=_done,
    )
    chat = PersistentChat(
        ag_session_id="session-missing-url-retained-tab",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=None,
    )

    async def quiescent(*, allow_recovering=False):
        return SimpleNamespace()

    chat.wait_quiescent = quiescent  # type: ignore[method-assign]

    await chat.open()

    assert chat.page_handle == "retained-handle"
    assert chat.state is ChatState.READY


@pytest.mark.asyncio
async def test_resume_open_fails_cleanly_without_orphaning_page_when_no_tab_or_url() -> None:
    """Missing chat-url AND no retained tab must fail before claiming a fresh page."""
    config = GptAutoConfig.from_dict(valid_config())

    create_page_calls: list[str] = []

    async def create_chat_page() -> str:
        create_page_calls.append("called")
        return "orphan-handle"

    async def find_conversation_page(_provider_session_id, *, preferred_target_id=None):
        return None

    runtime = SimpleNamespace(
        gpt_browser=SimpleNamespace(),
        bridge=SimpleNamespace(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
        find_conversation_page=find_conversation_page,
        create_chat_page=create_chat_page,
        register_chat=lambda _chat: _done(),
        claim_conversation=lambda _chat, _provider_session_id: True,
        ensure_available=_done,
    )
    chat = PersistentChat(
        ag_session_id="session-missing-url-no-tab",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=None,
    )

    with pytest.raises(RuntimeError, match="retained browser tab or a durable chat-url"):
        await chat.open()

    assert create_page_calls == []
    assert chat.page_handle is None
    # open() closes the chat on any _open_impl failure (FAILED -> CLOSED);
    # the important assertion is that no page was ever created/claimed.
    assert chat.state is ChatState.CLOSED


@pytest.mark.asyncio
async def test_open_recovers_without_hanging_despite_bridge_replacement_mid_resume() -> None:
    """GP05 boundary case: a shared-bridge death during _open_impl()'s
    find_conversation_page() await must not make resume hang for the full
    recovery-timeout before it can even re-verify the page it was handed.

    This reproduces the exact vulnerable window the review flagged.
    _wait_ready() already tolerates RECOVERING (allow_recovering=True), but
    the very next call -- self.snapshot() re-verifying provider-session
    identity -- did not, so a bridge replacement racing the resume path used
    to force a needless ~30s wait on a signal nothing in this flow ever
    sets, before eventually failing anyway. Fixed by passing
    allow_recovering=True there too, consistent with _wait_ready()'s own
    call just above it. With the fix, resume completes promptly and
    re-verifies identity against a live snapshot rather than trusting the
    page dict blindly.
    """
    config = GptAutoConfig.from_dict(valid_config())
    stale_page = {
        "pageHandle": "handle-from-dead-bridge-generation",
        "targetId": "stale-target",
        "url": "https://chatgpt.com/g/g-p-project/c/provider-session",
    }

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return []

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle, target_id="stable-target")

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": stale_page["url"],
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 0,
                "assistantCount": 0,
                "domSignals": {},
                "errorPresent": False,
            }

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=_Bridge(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
        register_chat=lambda _chat: _done(),
        claim_conversation=lambda _chat, _provider_session_id: True,
        ensure_available=_done,
    )

    chat = PersistentChat(
        ag_session_id="session-race-bridge-death-mid-resume",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url="https://chatgpt.com/g/g-p-project/c/provider-session",
    )

    async def find_conversation_page_races_bridge_death(_provider_session_id, *, preferred_target_id=None):
        # Simulate the shared CDP bridge dying WHILE this lookup is in
        # flight -- runtime.recover() would call bridge_replaced() on every
        # registered chat at exactly this moment in a real race.
        chat.bridge_replaced()
        return stale_page

    runtime.find_conversation_page = find_conversation_page_races_bridge_death

    async def quiescent(*, allow_recovering=False):
        assert allow_recovering is True
        return SimpleNamespace()

    chat.wait_quiescent = quiescent  # type: ignore[method-assign]

    # Before the fix this raised RuntimeError("gpt-auto chat recovery timed
    # out") after a full config.cdp.recovery_timeout_seconds wait; the
    # bounded wait_for below proves it no longer hangs at all.
    await asyncio.wait_for(chat.open(), timeout=2.0)

    assert chat.state is ChatState.READY
    assert chat.page_handle == "handle-from-dead-bridge-generation"


@pytest.mark.asyncio
async def test_find_conversation_page_picks_deterministically_among_duplicate_tabs(
    monkeypatch,
) -> None:
    """GP04: two tabs genuinely displaying the same canonical conversation
    (e.g. a human manually opened a second tab) is tab-instance duplication,
    not conversation-identity ambiguity -- must not hard-refuse. Must never
    hop onto a tab a different live chat already owns, and must be stable
    across repeated calls rather than depending on list_pages ordering."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_id = 7
    same_conversation_pages = [
        {"pageHandle": "page-32", "targetId": "target-b", "windowId": 7, "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
        {"pageHandle": "page-17", "targetId": "target-a", "windowId": 7, "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
    ]

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return same_conversation_pages

    async def ensure_anchor() -> str:
        return "anchor"

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    monkeypatch.setattr(runtime, "ensure_dedicated_window_anchor", ensure_anchor)

    # Neither tab is owned by another chat: pick deterministically (lowest
    # page handle), not whatever list_pages happened to return first.
    page = await runtime.find_conversation_page("provider-session")
    assert page is not None
    assert page["pageHandle"] == "page-17"

    # Repeated calls are stable.
    page_again = await runtime.find_conversation_page("provider-session")
    assert page_again["pageHandle"] == "page-17"


@pytest.mark.asyncio
async def test_find_conversation_page_never_hops_onto_a_page_owned_by_another_live_chat(
    monkeypatch,
) -> None:
    """A duplicate tab already claimed by a different live chat must never
    be silently selected -- that would bypass the ownership invariant
    _page_owners exists to enforce."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_id = 7
    same_conversation_pages = [
        {"pageHandle": "page-17", "targetId": "target-a", "windowId": 7, "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
        {"pageHandle": "page-32", "targetId": "target-b", "windowId": 7, "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
    ]
    # page-17 has the lower handle (would win the deterministic tiebreak),
    # but it's already owned by a different chat -- must be skipped.
    runtime._page_owners["page-17"] = "other-session"

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return same_conversation_pages

    async def ensure_anchor() -> str:
        return "anchor"

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    monkeypatch.setattr(runtime, "ensure_dedicated_window_anchor", ensure_anchor)

    page = await runtime.find_conversation_page("provider-session")
    assert page is not None
    assert page["pageHandle"] == "page-32"


def test_dedicated_window_ownership_rejects_duplicate_url_in_manual_window() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime._dedicated_window_id = 41

    assert runtime.page_belongs_to_dedicated_window({"windowId": 41})
    assert not runtime.page_belongs_to_dedicated_window({"windowId": 99})


@pytest.mark.asyncio
async def test_ensure_ready_recovers_when_bridge_replacement_races_binding_validation() -> None:
    """GP05 boundary case #2: a shared-bridge death during ensure_ready()'s
    admission-time _validate_page_binding() call.

    _validate_page_binding() reads its own local `page`/`handle` snapshot
    before a concurrent bridge_replaced() could fire, so it can take its
    "not recycled, not wrong conversation -> return early" path even though
    self.page_handle/self.state were already reset out from under it. This
    test proves ensure_ready()'s own fresh state re-check right after that
    call is what actually saves this window -- it must still reach READY via
    reconciliation, not silently proceed as if nothing happened, and not
    raise an opaque "chat is not ready" error.
    """
    config = GptAutoConfig.from_dict(valid_config())
    original_handle = "handle-from-dying-bridge"
    matching_url = "https://chatgpt.com/g/g-p-project/c/provider-session"

    class _Browser:
        async def page_by_handle(self, handle):
            # Simulate the shared bridge dying WHILE this lookup is in
            # flight -- runtime.recover() would call bridge_replaced() on
            # every registered chat at exactly this moment in a real race.
            chat.bridge_replaced()
            # The returned page object still looks like a normal match
            # (same target/url) from _validate_page_binding()'s point of
            # view -- it has no way to see that the bridge generation
            # underneath it has already changed.
            return SimpleNamespace(handle=handle, target_id="stable-target", url=matching_url)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": matching_url,
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 0,
                "assistantCount": 0,
                "domSignals": {},
                "errorPresent": False,
            }

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [{"pageHandle": "reconciled-handle", "targetId": "stable-target", "url": matching_url}]

    async def find_conversation_page(_provider_session_id, *, preferred_target_id=None):
        return {"pageHandle": "reconciled-handle", "targetId": "stable-target", "url": matching_url}

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=_Bridge(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
        find_conversation_page=find_conversation_page,
        page_belongs_to_dedicated_window=lambda _record: True,
    )

    chat = PersistentChat(
        ag_session_id="session-race-bridge-death-mid-admission",
        project_name="project",
        project_url=None,
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=matching_url,
    )
    chat.page_handle = original_handle
    chat.target_id = "stable-target"
    chat.state = ChatState.READY

    async def quiescent(*, allow_recovering=False):
        return SimpleNamespace()

    chat.wait_quiescent = quiescent  # type: ignore[method-assign]

    # Before a fix would be needed here, the risk is an unbounded hang or an
    # opaque "chat is not ready" RuntimeError; bound it to prove neither.
    await asyncio.wait_for(chat.ensure_ready(), timeout=2.0)

    assert chat.state is ChatState.READY
    assert chat.page_handle == "reconciled-handle", (
        "ensure_ready() must reconcile onto a page handle from the NEW "
        "bridge generation, never keep using the stale pre-race handle"
    )


def test_terminal_conversation_owner_can_be_reclaimed_by_resume() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime._conversation_owners["provider-session"] = "old-session"
    runtime._chats["old-session"] = SimpleNamespace(state=ChatState.FAILED)
    replacement = SimpleNamespace(ag_session_id="new-session")

    assert runtime.claim_conversation(replacement, "provider-session") is True
    assert runtime._conversation_owners["provider-session"] == "new-session"


@pytest.mark.asyncio
async def test_find_conversation_page_restores_window_before_selecting_retained_tab(
    monkeypatch,
) -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    calls: list[str] = []

    async def ensure_anchor() -> str:
        calls.append("anchor")
        runtime._dedicated_window_id = 7
        return "anchor"

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            calls.append("pages")
            return [
                {
                    "pageHandle": "manual-copy",
                    "targetId": "target-manual",
                    "windowId": 99,
                    "url": "https://chatgpt.com/g/g-p-project/c/provider-session",
                },
                {
                    "pageHandle": "retained",
                    "targetId": "target-retained",
                    "windowId": 7,
                    "url": "https://chatgpt.com/g/g-p-project/c/provider-session",
                },
            ]

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    monkeypatch.setattr(runtime, "ensure_dedicated_window_anchor", ensure_anchor)

    page = await runtime.find_conversation_page(
        "provider-session",
        preferred_target_id="target-retained",
    )

    assert calls == ["anchor", "pages"]
    assert page is not None
    assert page["pageHandle"] == "retained"


@pytest.mark.asyncio
async def test_find_conversation_page_does_not_trust_recycled_target_id(
    monkeypatch,
) -> None:
    """A recycled target must not bind a different ChatGPT conversation."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE

    async def ensure_anchor() -> str:
        runtime._dedicated_window_id = 7
        return "anchor"

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [
                {
                    "pageHandle": "recycled",
                    "targetId": "target-retained",
                    "windowId": 7,
                    "url": "https://chatgpt.com/g/g-p-project/c/a-different-conversation",
                },
                {
                    "pageHandle": "matching",
                    "targetId": "target-matching",
                    "windowId": 7,
                    "url": "https://chatgpt.com/g/g-p-project/c/provider-session",
                },
            ]

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    monkeypatch.setattr(runtime, "ensure_dedicated_window_anchor", ensure_anchor)

    page = await runtime.find_conversation_page(
        "provider-session",
        preferred_target_id="target-retained",
    )

    assert page is not None
    assert page["pageHandle"] == "matching"


@pytest.mark.asyncio
async def test_reconcile_proves_quiescence_before_ready(monkeypatch) -> None:
    config = GptAutoConfig.from_dict(valid_config())
    page = {
        "pageHandle": "retained",
        "targetId": "target-retained",
        "url": "https://chatgpt.com/c/provider-session",
    }

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [page]

    async def find_page(_provider_session_id, *, preferred_target_id=None):
        return page

    runtime = SimpleNamespace(
        bridge=_Bridge(),
        find_conversation_page=find_page,
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-recovering",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
    )
    chat.state = ChatState.RECOVERING
    observed: list[bool] = []

    async def quiescent(*, allow_recovering=False):
        observed.append(allow_recovering)
        return SimpleNamespace()

    monkeypatch.setattr(chat, "wait_quiescent", quiescent)

    await chat.ensure_ready()

    assert observed == [True]
    assert chat.state is ChatState.READY
    assert chat.page_handle == "retained"
    assert chat.target_id == "target-retained"


@pytest.mark.asyncio
async def test_ensure_ready_rebinds_when_external_cdp_close_invalidates_handle(monkeypatch) -> None:
    """An operator-side tab close must recover before a new prompt is sent."""
    config = GptAutoConfig.from_dict(valid_config())
    replacement = {
        "pageHandle": "replacement-handle",
        "targetId": "stable-target",
        "url": "https://chatgpt.com/g/g-p-project/project",
    }

    class _Browser:
        async def page_by_handle(self, handle):
            if handle == "stale-handle":
                raise RuntimeError("unknown or closed page handle: stale-handle")
            return SimpleNamespace(handle=handle, target_id="stable-target", url=replacement["url"])

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [replacement]

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=_Bridge(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-external-close",
        project_name="project",
        project_url=replacement["url"],
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "stale-handle"
    chat.target_id = "stable-target"
    chat.state = ChatState.READY

    async def quiescent(*, allow_recovering=False):
        assert allow_recovering is True
        return SimpleNamespace()

    monkeypatch.setattr(chat, "wait_quiescent", quiescent)

    await chat.ensure_ready()

    assert chat.page_handle == "replacement-handle"
    assert chat.target_id == "stable-target"
    assert chat.state is ChatState.READY


@pytest.mark.asyncio
async def test_active_reconcile_prefers_stable_target_before_stale_url() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    runtime = SimpleNamespace(
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-active-recovery",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.state = ChatState.RECOVERING
    chat.active_turn_id = "turn-1"
    chat.target_id = "stable-target"
    chat._last_url = "https://chatgpt.com/g/g-p-project/project"

    await chat.reconcile(
        [
            {
                "pageHandle": "replacement-handle",
                "targetId": "stable-target",
                "url": "https://chatgpt.com/g/g-p-project/c/new-conversation",
            }
        ]
    )

    assert chat.page_handle == "replacement-handle"
    assert chat.target_id == "stable-target"
    assert chat.state is ChatState.BUSY


@pytest.mark.asyncio
async def test_lazy_recovery_reacquires_ambiguous_first_turn_target(monkeypatch) -> None:
    config = GptAutoConfig.from_dict(valid_config())
    runtime = SimpleNamespace(
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-ambiguous-first-turn",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.state = ChatState.RECOVERING
    chat.target_id = "retained-target"
    chat.active_turn_id = None
    observed: list[bool] = []

    async def quiescent(*, allow_recovering=False):
        observed.append(allow_recovering)
        return SimpleNamespace()

    monkeypatch.setattr(chat, "wait_quiescent", quiescent)

    await chat.reconcile(
        [
            {
                "pageHandle": "retained-handle",
                "targetId": "retained-target",
                "url": "https://chatgpt.com/g/g-p-project/c/new-conversation",
            }
        ]
    )

    assert observed == [True]
    assert chat.page_handle == "retained-handle"
    assert chat.state is ChatState.READY


@pytest.mark.asyncio
async def test_anchor_rediscovery_reuses_only_the_gateway_http_page(monkeypatch) -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [
                {
                    "pageHandle": "legacy",
                    "url": "data:text/html,old-dashboard",
                    "title": "Agent gateway",
                    "windowId": 1,
                },
                {
                    "pageHandle": "anchor",
                    "url": gateway_dashboard_url(),
                    "title": "Gateway dashboard",
                    "windowId": 7,
                },
            ]

    runtime._bridge = _Bridge()  # type: ignore[assignment]

    async def available():
        return None

    monkeypatch.setattr(runtime, "ensure_available", available)

    assert await runtime.ensure_dedicated_window_anchor() == "anchor"
    assert runtime._dedicated_window_id == 7


@pytest.mark.asyncio
async def test_anchor_rediscovery_prefers_marked_dashboard_tab_and_normalizes_url(monkeypatch) -> None:
    """A restart can recover a marked or decorated dashboard tab by URL."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [
                {"pageHandle": "bare", "url": f"{gateway_dashboard_url()}/?old=1", "windowId": 4},
                {"pageHandle": "marked", "url": gateway_dashboard_anchor_url(), "windowId": 9},
            ]

    runtime._bridge = _Bridge()  # type: ignore[assignment]

    async def available():
        return None

    monkeypatch.setattr(runtime, "ensure_available", available)

    assert await runtime.ensure_dedicated_window_anchor() == "marked"
    assert runtime._dedicated_window_id == 9


@pytest.mark.asyncio
async def test_legacy_dashboard_tab_is_not_reused_or_repointed(monkeypatch) -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    calls: list[tuple[str, object]] = []

    class _Bridge:
        async def call(self, method, params=None):
            calls.append((method, params))
            if method == "list_pages":
                return [{"pageHandle": "legacy", "url": "data:text/html,old", "title": "Agent gateway", "windowId": 1}]
            if method == "create_window_page":
                return {"pageHandle": "new-anchor", "windowId": 2}
            assert method == "navigate"
            return {"ok": True}

    runtime._bridge = _Bridge()  # type: ignore[assignment]

    async def available():
        return None

    monkeypatch.setattr(runtime, "ensure_available", available)

    assert await runtime.ensure_dedicated_window_anchor() == "new-anchor"
    assert calls[-1] == (
        "navigate", {"pageHandle": "new-anchor", "url": gateway_dashboard_anchor_url()}
    )


async def _done() -> None:
    return None


async def _pages():
    return [{"pageHandle": "page-1", "targetId": "new-target"}]


@pytest.mark.asyncio
async def test_unregister_chat_has_no_dashboard_browser_side_effect() -> None:
    """The gateway owns status rendering; provider teardown only releases chat ownership."""
    config = GptAutoConfig.from_dict(valid_config())
    runtime = GptAutoProviderRuntime(config)
    runtime._dedicated_window_anchor = "anchor"
    runtime._bridge = SimpleNamespace()  # type: ignore[assignment]
    chat = SimpleNamespace(ag_session_id="s1", page_handle=None, provider_session_id=None)
    runtime._chats["s1"] = chat  # type: ignore[assignment]

    runtime.unregister_chat(chat)  # type: ignore[arg-type]

    assert runtime._chats == {}


@pytest.mark.asyncio
async def test_ensure_dedicated_window_anchor_is_not_a_dashboard_refresh_path(monkeypatch) -> None:
    config = GptAutoConfig.from_dict(valid_config())
    runtime = GptAutoProviderRuntime(config)
    runtime._dedicated_window_anchor = "anchor"
    runtime._dedicated_window_id = 7

    order: list[str] = []

    class _Bridge:
        async def call(self, method, params=None, **kwargs):
            order.append(f"bridge-{method}")
            if method == "list_pages":
                return [{"pageHandle": "anchor", "url": gateway_dashboard_url(), "windowId": 7}]
            return {"ok": True}

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    async def available():
        return None

    monkeypatch.setattr(runtime, "ensure_available", available)

    result = await runtime.ensure_dedicated_window_anchor()
    assert result == "anchor"
    assert order == ["bridge-list_pages"]
