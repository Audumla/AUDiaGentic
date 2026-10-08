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
    _ConversationLoadFailure,
    _unresolved_prompt_match,
    _unresolved_prompt_match_diagnostics,
)
from audiagentic.components.providers.adapters.gpt_auto.turn import _scalar_binding_metadata
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import (
    PromptFingerprint,
)
from audiagentic.components.providers.adapters.gpt_auto.runtime import (
    GptAutoProviderRuntime,
    ProviderState,
)
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatMessageRef, ChatSnapshot
from audiagentic.components.providers.adapters.gpt_auto.window_anchor import (
    gateway_dashboard_anchor_url,
    gateway_dashboard_url,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_greenfield_config_urls import valid_config


@pytest.mark.asyncio
async def test_unavailable_remote_cdp_never_starts_a_local_browser(monkeypatch) -> None:
    value = valid_config()
    value["cdp"]["endpoint"] = "http://192.0.2.10:9222"
    value["browser"]["executable"] = r"C:\remote-browser-is-not-used.exe"
    config = GptAutoConfig.from_dict(value)
    runtime = GptAutoProviderRuntime(config)
    launched = False

    async def unavailable() -> bool:
        return False

    async def should_not_launch():
        nonlocal launched
        launched = True
        raise AssertionError("remote CDP must not launch a local browser")

    monkeypatch.setattr(runtime, "_cdp_available", unavailable)
    monkeypatch.setattr(runtime._browser, "ensure_browser_for_cdp", should_not_launch)

    with pytest.raises(RuntimeError, match="configured remote CDP endpoint is unavailable"):
        await runtime.ensure_available()

    assert not launched
    assert runtime.state is ProviderState.FAILED


@pytest.mark.asyncio
async def test_cdp_readiness_probes_the_configured_endpoint(monkeypatch) -> None:
    value = valid_config()
    value["cdp"]["endpoint"] = "http://192.0.2.10:9444"
    config = GptAutoConfig.from_dict(value)
    runtime = GptAutoProviderRuntime(config)
    calls = []

    class _Writer:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def open_connection(host, port):
        calls.append((host, port))
        return object(), _Writer()

    monkeypatch.setattr(runtime_module.asyncio, "open_connection", open_connection)

    assert await runtime._cdp_available()
    assert calls == [("192.0.2.10", 9444)]


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


@pytest.mark.asyncio
async def test_conversation_title_is_relayed_once_and_bounded() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    updates = []
    chat = PersistentChat(
        ag_session_id="session-title",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda update: updates.append(update),
        provider_session_id="provider-session",
    )

    await chat.publish_conversation_title("  Repository review  ")
    await chat.publish_conversation_title("Repository review")
    await chat.publish_conversation_title("x" * 400)

    assert [update.metadata for update in updates] == [
        {"chat-title": "Repository review"},
        {"chat-title": "x" * 256},
    ]


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


def test_unresolved_recovery_accepts_renderer_structural_hr_correlation() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    source = "before\n---\nafter"
    chat = PersistentChat(
        ag_session_id="session-structural-correlation",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.mark_submission_unresolved(source)
    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=1,
        latest_assistant_id="assistant-1",
        latest_user_text="before\nafter",
        latest_assistant_text="done",
        dom_signals=frozenset(),
        error_present=False,
        message_refs=(
            ChatMessageRef(
                role="user",
                message_id="user-1",
                text="before\nafter",
                correlation_text=source,
                structural_hr_count=1,
                sequence=0,
            ),
        ),
    )

    match, reason, details = _unresolved_prompt_match_diagnostics(chat, snapshot)

    assert match == f"text:{PromptFingerprint.from_text(source).digest}"
    assert reason == "prompt-text-digest-match"
    assert details["prompt-correlation-match"] is True
    assert details["prompt-proof-source"] == "gpt-auto-dom-structural-v1"
    assert details["structural-hr-count"] == 1


def test_unresolved_recovery_rejects_substantive_structural_candidate_mismatch() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    chat = PersistentChat(
        ag_session_id="session-structural-mismatch",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.mark_submission_unresolved("before\n---\nafter")
    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=1,
        latest_assistant_id="assistant-1",
        latest_user_text="before\nafter",
        latest_assistant_text="done",
        dom_signals=frozenset(),
        error_present=False,
        message_refs=(
            ChatMessageRef(
                role="user",
                message_id="user-1",
                text="before\nafter",
                correlation_text="before\n---\nchanged",
                structural_hr_count=1,
                sequence=0,
            ),
        ),
    )

    match, reason, _details = _unresolved_prompt_match_diagnostics(chat, snapshot)

    assert match is None
    assert reason == "prompt-text-digest-not-found"


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
        error_alert_occurrences=(("baseline-alert", None),),
    )

    await chat.persist_unresolved_checkpoint(turn_id="turn-1", baseline=baseline)

    assert updates[-1]["unresolved-baseline-user-count"] == 3
    assert updates[-1]["unresolved-baseline-assistant-count"] == 2
    assert updates[-1]["unresolved-baseline-error-alert-occurrences"] == [
        {"digest": "baseline-alert", "ownerPromptMessageId": None}
    ]


def test_binding_metadata_projection_drops_structured_checkpoint_evidence() -> None:
    metadata = {
        "prompt-message-id": "prompt-1",
        "submission-proven": True,
        "prompt-text-digest": "f" * 64,
        "unresolved-baseline-error-alert-occurrences": [
            {"digest": "alert", "ownerPromptMessageId": None}
        ],
    }

    assert _scalar_binding_metadata(metadata) == {
        "prompt-message-id": "prompt-1",
        "submission-proven": True,
        "prompt-text-digest": "f" * 64,
    }
    assert metadata["unresolved-baseline-error-alert-occurrences"]


@pytest.mark.asyncio
async def test_request_metadata_sink_can_be_rebound_for_each_turn() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    first_updates = []
    second_updates = []
    chat = PersistentChat(
        ag_session_id="session-turn-sink",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        checkpoint_sink=first_updates.append,
    )
    baseline = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=True,
        composer_editable=True,
        user_count=0,
        assistant_count=0,
        latest_user_text=None,
        latest_assistant_id=None,
        latest_assistant_text=None,
        dom_signals=frozenset(),
        error_present=False,
    )

    chat.set_request_metadata_sink(second_updates.append)
    chat.mark_prompt_submitted("prompt-2", None, "second turn")
    await chat.persist_unresolved_checkpoint(turn_id="turn-2", baseline=baseline)

    assert first_updates[-1]["submission-proven"] is True
    assert second_updates[-1]["submission-proven"] is True
    assert second_updates[-1]["prompt-message-id"] == "prompt-2"


@pytest.mark.asyncio
async def test_fifo_turns_share_session_checkpoint_but_isolate_request_sinks() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    session_updates = []
    request_a_updates = []
    request_b_updates = []
    chat = PersistentChat(
        ag_session_id="session-fifo-sinks",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        checkpoint_sink=session_updates.append,
    )
    baseline = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=True,
        composer_editable=True,
        user_count=0,
        assistant_count=0,
        latest_user_text=None,
        latest_assistant_id=None,
        latest_assistant_text=None,
        dom_signals=frozenset(),
        error_present=False,
    )

    chat.set_request_metadata_sink(request_a_updates.append)
    chat.mark_prompt_submitted("prompt-a", None, "turn A")
    await chat.persist_unresolved_checkpoint(turn_id="turn-a", baseline=baseline)

    chat.set_request_metadata_sink(request_b_updates.append)
    chat.mark_submission_unresolved("turn B")
    await chat.persist_unresolved_checkpoint(turn_id="turn-b", baseline=baseline)

    assert len(session_updates) == 2
    assert len(request_a_updates) == 1
    assert len(request_b_updates) == 1
    assert request_a_updates[0]["unresolved-turn-id"] == "turn-a"
    assert request_b_updates[0]["unresolved-turn-id"] == "turn-b"
    assert session_updates[-1]["unresolved-turn-id"] == "turn-b"


def test_new_submission_fence_clears_predecessor_identity() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    chat = PersistentChat(
        ag_session_id="session-turn-fence",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
    )

    chat.mark_prompt_submitted("old-prompt", "old-assistant", "old turn")
    chat.mark_assistant_observed("old-answer")
    chat.mark_submission_unresolved("new turn")

    metadata = chat.unresolved_metadata()
    assert metadata["submission-proven"] is False
    assert "prompt-message-id" not in metadata
    assert "assistant-message-id" not in metadata
    assert "assistant-before-message-id" not in metadata
    assert metadata["prompt-text-digest"] == PromptFingerprint.from_text("new turn").digest


@pytest.mark.asyncio
async def test_terminal_checkpoint_clear_retains_submission_proof() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    updates = []
    chat = PersistentChat(
        ag_session_id="session-terminal-proof",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        checkpoint_sink=updates.append,
    )

    chat.mark_prompt_submitted("prompt-1", "assistant-0", "turn")
    chat.mark_assistant_observed("assistant-1")
    await chat.persist_unresolved_clear()

    assert updates[-1] == {
        "unresolved-turn-pending": False,
        "submission-proven": True,
        "prompt-message-id": "prompt-1",
        "assistant-message-id": "assistant-1",
        "assistant-before-message-id": "assistant-0",
        "prompt-text-digest": chat.unresolved_prompt_text_digest,
    }


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


def test_rehydrated_chat_hydrates_preferred_cdp_target_id() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    chat = PersistentChat(
        ag_session_id="session-target-rehydrate",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url="https://chatgpt.com/g/g-p-project/c/provider-session",
        resume_provider_metadata={"target-id": "target-original"},
    )

    assert chat.target_id == "target-original"
    assert chat.unresolved_metadata()["target-id"] == "target-original"


@pytest.mark.asyncio
async def test_rehydrated_transport_refreshes_target_binding_without_prompt() -> None:
    updates = []

    async def binding_sink(update) -> None:
        updates.append(update)

    async def open_chat() -> None:
        return None

    chat = SimpleNamespace(
        open=open_chat,
        project_url="https://chatgpt.com/g/g-p-project/project",
        unresolved_metadata=lambda: {"target-id": "target-fallback"},
        provider_session_id="provider-session",
        chat_url="https://chatgpt.com/g/g-p-project/c/provider-session",
        target_id="target-fallback",
        binding_sink=binding_sink,
        ag_session_id="session-target-refresh",
    )

    result = await GptAutoSessionTransport(chat).open()

    assert result.provider_session_ref is not None
    assert result.provider_session_ref.value == "provider-session"
    assert len(updates) == 1
    assert updates[0].metadata["target-id"] == "target-fallback"


@pytest.mark.asyncio
async def test_transport_maps_project_readiness_timeout_to_structured_provider_error() -> None:
    from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
        ProjectReadinessError,
    )

    readiness = ProjectReadinessError("project route did not materialize")
    readiness.details = {
        "reason": "project-route-not-materialized",
        "expected-project-id": "g-p-project",
    }

    async def open_chat() -> None:
        raise readiness

    chat = SimpleNamespace(open=open_chat, ag_session_id="session-project-readiness")

    with pytest.raises(AudiaGenticError) as raised:
        await GptAutoSessionTransport(chat).open()

    assert raised.value.code == "EXT-GPTAUTO-004"
    assert raised.value.details["failure-stage"] == "readiness"
    assert raised.value.details["submission-proven"] is False
    assert raised.value.details["reason"] == "project-route-not-materialized"


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
        "-or-completion-control+not-generating"
        "-or-canvas-edit-control+canvas-open-editor-control+not-generating"
    )


@pytest.mark.asyncio
async def test_unresolved_recovery_requires_owned_assistant_when_user_node_is_virtualized() -> None:
    """A completed background tab must retain request-owned correlation.

    ChatGPT can unmount the submitted user node after a failed observation
    pass.  The retained baseline assistant id plus a newer quiescent assistant
    response alone is ambiguous because another actor may have inserted it.
    A previously captured request-owned assistant id is sufficient.
    """
    config = GptAutoConfig.from_dict(valid_config())
    config = replace(config, turn=replace(config.turn, response_stability_seconds=0.0))

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": "https://chatgpt.com/g/g-p-project/c/conversation-1",
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 2,
                "assistantCount": 2,
                "latestAssistantId": "assistant-new",
                "latestAssistantText": "completed response from the background tab",
                # The submitted user node is not mounted in this snapshot.
                "latestUserText": "older visible prompt",
                "userMessageTexts": ["older visible prompt"],
                "domSignals": {"completion-control": True, "more-actions-menu": True},
                "generating": False,
                "errorPresent": False,
            }

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=SimpleNamespace(),
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-virtualized-user",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="conversation-1",
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.RECOVERING
    chat.mark_prompt_submitted("prompt-new", "assistant-before", "submitted prompt")

    assert await chat._reconcile_unresolved_turn() is False
    assert chat._unresolved_recovery_reason == "prompt-text-digest-not-found"
    assert chat.unresolved_turn_pending is True

    chat.unresolved_assistant_message_id = "assistant-new"
    # The first correlated observation arms the stability fingerprint; the
    # second proves that the response remained unchanged.
    assert await chat._reconcile_unresolved_turn() is False
    assert await chat._reconcile_unresolved_turn() is True
    chat._move(ChatState.READY)
    assert chat.unresolved_turn_pending is False
    assert chat.state is ChatState.READY


@pytest.mark.asyncio
async def test_unresolved_recovery_reconciles_despite_stuck_generating_signal() -> None:
    """Live-reproduced 2026-08-16 (GP05 L4 scenario): reconciliation of an
    unresolved turn must not be permanently blocked by a stuck
    generating=True/stop-control signal once real completion evidence
    (completion-control here) corroborates that the response is done --
    matches the composer-editable=True + stop-control-stuck combination
    observed live, which is itself evidence the button state is stale."""
    config = GptAutoConfig.from_dict(valid_config())
    object.__setattr__(config.turn, "response_generating_override_stability_seconds", 0.01)

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

    # Admission now owns the bounded wait for the required second stable
    # observation. A queued successor does not fail merely because its first
    # recovery poll armed the stability window.
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


def test_provider_quiescent_ignores_stale_stop_control_after_completion() -> None:
    """A completed ChatGPT turn may leave its stop button mounted.

    The provider's explicit ``generating`` state and real busy indicators are
    authoritative.  A stale stop control must not strand a persistent session
    at readiness and turn every later request into a false quiescence failure.
    """
    from audiagentic.components.providers.adapters.gpt_auto.chat import provider_quiescent
    from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/project",
        composer_present=True,
        composer_editable=True,
        generating=False,
        error_present=False,
        dom_signals=frozenset({"stop-control", "completion-control", "more-actions-menu"}),
        user_count=1,
        assistant_count=1,
        latest_assistant_id="assistant-1",
        latest_user_text="request",
        latest_assistant_text="done",
    )

    assert provider_quiescent(snapshot) is True


def test_provider_quiescent_treats_document_alert_as_advisory() -> None:
    from audiagentic.components.providers.adapters.gpt_auto.chat import provider_quiescent
    from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/project",
        composer_present=True,
        composer_editable=True,
        generating=False,
        error_present=False,
        dom_signals=frozenset({"error-alert"}),
        user_count=1,
        assistant_count=1,
        latest_assistant_id="assistant-1",
        latest_user_text="request",
        latest_assistant_text="done",
    )
    assert provider_quiescent(snapshot) is True


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
async def test_find_conversation_page_falls_back_to_exact_tab_in_prior_window(
    monkeypatch,
) -> None:
    """A restart may leave the retained conversation outside the new anchor window."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_id = 7

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return [
                {
                    "pageHandle": "retained-prior-window",
                    "targetId": "target-retained",
                    "windowId": 99,
                    "url": "https://chatgpt.com/g/g-p-project/c/provider-session",
                }
            ]

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    monkeypatch.setattr(runtime, "ensure_dedicated_window_anchor", lambda: asyncio.sleep(0, result="anchor"))

    page = await runtime.find_conversation_page("provider-session")

    assert page is not None
    assert page["pageHandle"] == "retained-prior-window"


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
async def test_reconcile_replaces_retained_conversation_load_error_without_resubmit() -> None:
    """A broken retained renderer is replaced without replaying the prompt."""
    config = GptAutoConfig.from_dict(valid_config())
    chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    retained = {"pageHandle": "retained-error", "targetId": "error-target", "url": chat_url}
    replacement = {"pageHandle": "replacement", "targetId": "replacement-target", "url": chat_url}
    owned: set[str] = set()
    released: list[str] = []
    navigated: list[str] = []
    closed: list[str] = []

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(
                handle=handle,
                target_id="error-target" if handle == retained["pageHandle"] else "replacement-target",
                url=chat_url,
            )

        async def snapshot(self, page, *, signals=None):
            return {
                "url": chat_url,
                "composerPresent": page.handle != retained["pageHandle"],
                "composerEditable": page.handle != retained["pageHandle"],
                "userCount": 0,
                "assistantCount": 0,
                "domSignals": (
                    {"conversation-load-failed": True}
                    if page.handle == retained["pageHandle"]
                    else {}
                ),
                "errorPresent": page.handle == retained["pageHandle"],
            }

    class _Bridge:
        async def call(self, method, params=None, **kwargs):
            if method == "navigate":
                navigated.append(str((params or {}).get("url")))
                return None
            if method == "close_page":
                closed.append(str((params or {}).get("pageHandle")))
                return None
            if method == "list_pages":
                return [retained]
            raise AssertionError(method)

    async def find_page(_provider_session_id, *, preferred_target_id=None):
        return retained

    async def create_page() -> str:
        return replacement["pageHandle"]

    def claim(_chat, handle: str) -> bool:
        if handle in owned:
            return False
        owned.add(handle)
        return True

    def release(_chat, handle: str) -> None:
        released.append(handle)
        owned.discard(handle)

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=_Bridge(),
        find_conversation_page=find_page,
        create_chat_page=create_page,
        claim_page=claim,
        release_page=release,
    )
    chat = PersistentChat(
        ag_session_id="session-load-error-recovery",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=chat_url,
    )
    chat.state = ChatState.RECOVERING
    chat.unresolved_turn_pending = True
    chat.defer_unresolved_reconciliation()

    await chat.reconcile([retained])

    assert chat.page_handle == retained["pageHandle"]
    assert retained["pageHandle"] not in released
    assert navigated == []
    assert closed == []
    # Deferred recovery keeps the consumed budget until the unresolved turn
    # reaches terminal cleanup; a delayed provider load error must not reopen
    # another full replacement budget after restart.
    assert chat._conversation_load_recovery_attempts == 0


@pytest.mark.asyncio
async def test_ensure_ready_does_not_treat_repeated_load_error_inspection_as_progress() -> None:
    """A bound submitted load-error page remains observation-only."""
    config = GptAutoConfig.from_dict(valid_config())
    chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    failed = ChatSnapshot(
        url=chat_url,
        composer_present=False,
        composer_editable=False,
        user_count=0,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text=None,
        latest_assistant_text=None,
        dom_signals=frozenset({"conversation-load-failed"}),
        error_present=True,
    )
    chat = PersistentChat(
        ag_session_id="session-load-error-admission",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=chat_url,
        resume_provider_metadata={"conversation-load-recovery-attempts": 2},
    )
    chat.page_handle = "retained-error"
    chat.state = ChatState.RECOVERING
    chat.unresolved_turn_pending = True
    chat.defer_unresolved_reconciliation()
    replacements: list[ChatSnapshot | None] = []

    async def validate_binding() -> None:
        return None

    async def retained_snapshot() -> ChatSnapshot:
        return failed

    async def exhausted_replacement(snapshot: ChatSnapshot | None) -> bool:
        replacements.append(snapshot)
        return False

    chat._validate_page_binding = validate_binding  # type: ignore[method-assign]
    chat._retained_page_snapshot = retained_snapshot  # type: ignore[method-assign]
    chat._replace_load_failed_page = exhausted_replacement  # type: ignore[method-assign]

    await chat.ensure_ready()

    assert replacements == [failed]
    assert chat.state is ChatState.READY


@pytest.mark.asyncio
async def test_ensure_ready_preserves_replacement_load_error_dom_evidence() -> None:
    """A replacement tab that also fails stays eligible for safe unsent retry."""
    config = GptAutoConfig.from_dict(valid_config())
    chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    failed = ChatSnapshot(
        url=chat_url,
        composer_present=False,
        composer_editable=False,
        user_count=0,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text=None,
        latest_assistant_text=None,
        dom_signals=frozenset({"conversation-load-failed"}),
        error_present=True,
    )
    chat = PersistentChat(
        ag_session_id="session-load-error-replacement",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=chat_url,
        resume_provider_metadata={"conversation-load-recovery-attempts": 0},
    )
    chat.page_handle = "retained-error"

    async def validate_binding() -> None:
        return None

    async def retained_snapshot() -> ChatSnapshot:
        return failed

    async def failed_replacement(_snapshot: ChatSnapshot | None) -> bool:
        raise _ConversationLoadFailure(failed)

    chat._validate_page_binding = validate_binding  # type: ignore[method-assign]
    chat._retained_page_snapshot = retained_snapshot  # type: ignore[method-assign]
    chat._replace_load_failed_page = failed_replacement  # type: ignore[method-assign]

    with pytest.raises(AudiaGenticError) as raised:
        await chat.ensure_ready()

    assert raised.value.code == "EXT-GPTAUTO-005"
    assert raised.value.details["dom-signals"] == ["conversation-load-failed"]
    assert raised.value.details["submission-proven"] is False
    assert raised.value.details["submission-ambiguous"] is False
    assert raised.value.details["submission-attempted"] is False
    assert chat.state is ChatState.FAILED


@pytest.mark.asyncio
async def test_conversation_load_recovery_budget_survives_chat_reconstruction() -> None:
    """A failed replacement consumes durable budget across new chat objects."""
    config = GptAutoConfig.from_dict(valid_config())
    checkpointed: list[dict[str, object]] = []
    failure = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=False,
        composer_editable=False,
        user_count=0,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text=None,
        latest_assistant_text=None,
        dom_signals=frozenset({"conversation-load-failed"}),
        error_present=True,
    )
    runtime = SimpleNamespace()

    async def checkpoint(metadata: dict[str, object]) -> None:
        checkpointed.append(dict(metadata))

    first = PersistentChat(
        ag_session_id="session-load-error-budget",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        checkpoint_sink=checkpoint,
        provider_session_id="provider-session",
        chat_url=failure.url,
        resume_provider_metadata={"conversation-load-recovery-attempts": 1},
    )

    async def fail_to_create_page() -> str:
        raise RuntimeError("replacement unavailable")

    first._create_recovery_page = fail_to_create_page  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="replacement unavailable"):
        await first._replace_load_failed_page(failure)
    assert checkpointed[-1]["conversation-load-recovery-attempts"] == 2

    second = PersistentChat(
        ag_session_id="session-load-error-budget",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        checkpoint_sink=checkpoint,
        provider_session_id="provider-session",
        chat_url=failure.url,
        resume_provider_metadata=checkpointed[-1],
    )
    assert second._conversation_load_recovery_attempts == 2
    assert await second._replace_load_failed_page(failure) is False
    healthy = replace(failure, dom_signals=frozenset(), error_present=False)
    assert await second._replace_load_failed_page(healthy) is False
    assert second._conversation_load_recovery_attempts == 2


@pytest.mark.asyncio
async def test_deferred_recovery_budget_survives_delayed_load_error() -> None:
    """A loadable replacement must not reset budget before a later error."""
    config = GptAutoConfig.from_dict(valid_config())
    chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    checkpointed: list[dict[str, object]] = []
    runtime = SimpleNamespace()

    async def checkpoint(metadata: dict[str, object]) -> None:
        checkpointed.append(dict(metadata))

    chat = PersistentChat(
        ag_session_id="session-delayed-load-error",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        checkpoint_sink=checkpoint,
        provider_session_id="provider-session",
        chat_url=chat_url,
    )
    chat.unresolved_turn_pending = True
    chat.defer_unresolved_reconciliation()

    healthy = ChatSnapshot(
        url=chat_url,
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text="prompt",
        latest_assistant_text=None,
        dom_signals=frozenset({"stop-control"}),
        error_present=False,
        generating=True,
    )
    failed = replace(
        healthy,
        composer_present=False,
        composer_editable=False,
        dom_signals=frozenset({"conversation-load-failed"}),
        error_present=True,
    )
    replacement_calls = 0

    async def create_recovery_page() -> str:
        nonlocal replacement_calls
        replacement_calls += 1
        return f"replacement-{replacement_calls}"

    async def navigate(*_args, **_kwargs) -> None:
        return None

    async def snapshot(*_args, **_kwargs) -> ChatSnapshot:
        return healthy

    chat._create_recovery_page = create_recovery_page  # type: ignore[method-assign]
    chat.runtime.bridge = SimpleNamespace(call=navigate)
    chat.snapshot = snapshot  # type: ignore[method-assign]
    chat._claim_page = lambda _handle: True  # type: ignore[method-assign]

    assert await chat._replace_load_failed_page(failed) is True
    assert chat._conversation_load_recovery_attempts == 0
    assert not checkpointed or checkpointed[-1].get("conversation-load-recovery-attempts", 0) == 0


@pytest.mark.asyncio
async def test_loadable_but_blank_replacement_does_not_clear_recovery_budget() -> None:
    """A URL-only replacement is not enough to reset recovery attempts."""
    config = GptAutoConfig.from_dict(valid_config())
    chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    chat = PersistentChat(
        ag_session_id="session-blank-replacement",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=SimpleNamespace(),
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=chat_url,
    )
    failed = ChatSnapshot(
        url=chat_url,
        composer_present=False,
        composer_editable=False,
        user_count=0,
        assistant_count=0,
        latest_assistant_id=None,
        latest_user_text=None,
        latest_assistant_text=None,
        dom_signals=frozenset({"conversation-load-failed"}),
        error_present=True,
    )
    blank = replace(failed, dom_signals=frozenset(), error_present=False)
    chat._create_recovery_page = lambda: asyncio.sleep(0, result="replacement")  # type: ignore[method-assign]
    chat._claim_page = lambda _handle: True  # type: ignore[method-assign]
    chat.runtime.release_page = lambda _chat, _handle: None
    chat.runtime.bridge = SimpleNamespace(call=lambda *args, **kwargs: asyncio.sleep(0))
    chat.snapshot = lambda **kwargs: asyncio.sleep(0, result=blank)  # type: ignore[method-assign]
    chat.wait_quiescent = lambda **kwargs: asyncio.sleep(0, result=blank)  # type: ignore[method-assign]

    assert await chat._replace_load_failed_page(failed) is True
    assert chat._conversation_load_recovery_attempts == 1


@pytest.mark.asyncio
async def test_prefer_active_conversation_page_preserves_healthy_durable_target() -> None:
    """DOM richness must not replace a healthy durable tab after restart."""
    config = GptAutoConfig.from_dict(valid_config())
    chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    pages = [
        {
            "pageHandle": "managed-rich",
            "targetId": "managed-target",
            "windowId": 7,
            "url": chat_url,
        },
        {
            "pageHandle": "prior-durable",
            "targetId": "durable-target",
            "windowId": 3,
            "url": chat_url,
        },
    ]

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, page, *, signals=None):
            count = 4 if page.handle == "managed-rich" else 1
            return {
                "url": chat_url,
                "composerPresent": True,
                "userCount": count,
                "assistantCount": count,
                "domSignals": {},
            }

    class _Bridge:
        async def call(self, method, params=None, **kwargs):
            assert method == "list_pages"
            return pages

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=_Bridge(),
        _page_owners={"managed-rich": "other-session"},
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-durable-preference",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=chat_url,
    )
    chat.page_handle = "prior-durable"
    chat.target_id = "durable-target"

    await chat._prefer_active_conversation_page()

    assert chat.page_handle == "prior-durable"
    assert chat.target_id == "durable-target"


@pytest.mark.asyncio
async def test_resume_open_attaches_to_generating_retained_tab_without_waiting_quiescence() -> None:
    """Restart recovery must attach while the provider is still reasoning."""
    config = GptAutoConfig.from_dict(valid_config())
    chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    retained = {"pageHandle": "retained-generating", "targetId": "generating-target", "url": chat_url}

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle, target_id="generating-target", url=chat_url)

        async def snapshot(self, _page, *, signals=None):
            return {
                "url": chat_url,
                "composerPresent": True,
                "composerEditable": True,
                "userCount": 1,
                "assistantCount": 0,
                "latestUserId": "prompt-id",
                "domSignals": {"stop-control": True},
                "errorPresent": False,
                "generating": True,
            }

    class _Bridge:
        async def call(self, method, params=None, **kwargs):
            assert method == "list_pages"
            return [retained]

    async def find_page(_provider_session_id, *, preferred_target_id=None):
        return retained

    runtime = SimpleNamespace(
        gpt_browser=_Browser(),
        bridge=_Bridge(),
        find_conversation_page=find_page,
        ensure_available=lambda: asyncio.sleep(0),
        register_chat=lambda _chat: asyncio.sleep(0),
        claim_conversation=lambda _chat, _provider_session_id: True,
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat = PersistentChat(
        ag_session_id="session-generating-recovery",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url=chat_url,
    )
    chat.unresolved_turn_pending = True
    chat.defer_unresolved_reconciliation()

    async def must_not_wait(*, allow_recovering=False):
        raise AssertionError("restart recovery must not wait for provider quiescence")

    chat.wait_quiescent = must_not_wait  # type: ignore[method-assign]

    await chat.open()

    assert chat.state is ChatState.READY
    assert chat.page_handle == retained["pageHandle"]


@pytest.mark.asyncio
async def test_find_conversation_page_prefers_healthy_duplicate_over_load_error(monkeypatch) -> None:
    """A later restart must select the healthy duplicate, not the broken tab."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_id = 7
    pages = [
        {"pageHandle": "error-page", "targetId": "error-target", "windowId": 7,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
        {"pageHandle": "healthy-page", "targetId": "healthy-target", "windowId": 7,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
    ]

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return pages

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, page, *, signals=None):
            return {"url": pages[0]["url"], "domSignals": {
                "conversation-load-failed": page.handle == "error-page"
            }}

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    runtime._gpt_browser = _Browser()  # type: ignore[assignment]
    monkeypatch.setattr(
        runtime,
        "ensure_dedicated_window_anchor",
        lambda: asyncio.sleep(0, result="anchor"),
    )

    selected = await runtime.find_conversation_page("provider-session")

    assert selected is not None
    assert selected["pageHandle"] == "healthy-page"


@pytest.mark.asyncio
async def test_find_conversation_page_does_not_mask_prior_window_healthy_tab(monkeypatch) -> None:
    """A failed managed tab cannot hide a healthy exact conversation elsewhere."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_id = 7
    pages = [
        {"pageHandle": "managed-error", "targetId": "managed-target", "windowId": 7,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
        {"pageHandle": "prior-healthy", "targetId": "prior-target", "windowId": 3,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
    ]

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return pages

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, page, *, signals=None):
            return {"url": pages[0]["url"], "domSignals": {
                "conversation-load-failed": page.handle == "managed-error"
            }}

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    runtime._gpt_browser = _Browser()  # type: ignore[assignment]
    monkeypatch.setattr(
        runtime,
        "ensure_dedicated_window_anchor",
        lambda: asyncio.sleep(0, result="anchor"),
    )

    selected = await runtime.find_conversation_page("provider-session")

    assert selected is not None
    assert selected["pageHandle"] == "prior-healthy"


@pytest.mark.asyncio
async def test_find_conversation_page_ranks_healthy_tab_over_unknown_managed_tab(monkeypatch) -> None:
    """A failed CDP probe is unknown and cannot mask positive prior-window health."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_id = 7
    pages = [
        {"pageHandle": "managed-unknown", "targetId": "managed-target", "windowId": 7,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
        {"pageHandle": "prior-healthy", "targetId": "prior-target", "windowId": 3,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
    ]

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return pages

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, page, *, signals=None):
            if page.handle == "managed-unknown":
                raise RuntimeError("stale CDP target")
            return {
                "url": pages[1]["url"],
                "composerPresent": True,
                "domSignals": {},
            }

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    runtime._gpt_browser = _Browser()  # type: ignore[assignment]
    monkeypatch.setattr(
        runtime,
        "ensure_dedicated_window_anchor",
        lambda: asyncio.sleep(0, result="anchor"),
    )

    selected = await runtime.find_conversation_page("provider-session")

    assert selected is not None
    assert selected["pageHandle"] == "prior-healthy"


@pytest.mark.asyncio
async def test_find_conversation_page_prefers_healthy_durable_target_across_windows(monkeypatch) -> None:
    """A healthy durable target remains preferred even after window recreation."""
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    runtime.state = ProviderState.AVAILABLE
    runtime._dedicated_window_id = 7
    pages = [
        {"pageHandle": "managed-duplicate", "targetId": "managed-target", "windowId": 7,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
        {"pageHandle": "prior-durable", "targetId": "durable-target", "windowId": 3,
         "url": "https://chatgpt.com/g/g-p-project/c/provider-session"},
    ]

    class _Bridge:
        async def call(self, method, params=None):
            assert method == "list_pages"
            return pages

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(handle=handle)

        async def snapshot(self, page, *, signals=None):
            return {
                "url": pages[0]["url"],
                "composerPresent": True,
                "domSignals": {},
            }

    runtime._bridge = _Bridge()  # type: ignore[assignment]
    runtime._gpt_browser = _Browser()  # type: ignore[assignment]
    monkeypatch.setattr(
        runtime,
        "ensure_dedicated_window_anchor",
        lambda: asyncio.sleep(0, result="anchor"),
    )

    selected = await runtime.find_conversation_page(
        "provider-session",
        preferred_target_id="durable-target",
    )

    assert selected is not None
    assert selected["pageHandle"] == "prior-durable"


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


@pytest.mark.asyncio
async def test_refresh_bound_conversation_refuses_revoked_owner_before_navigation() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    navigated: list[str] = []

    class _Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(
                handle=handle,
                target_id="target-1",
                url="https://chatgpt.com/g/g-p-project/c/provider-session",
            )

        async def navigate(self, _page, url):
            navigated.append(url)

    runtime = SimpleNamespace(gpt_browser=_Browser(), bridge=SimpleNamespace())
    chat = PersistentChat(
        ag_session_id="session-owner-fence",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url="https://chatgpt.com/g/g-p-project/c/provider-session",
    )
    chat.page_handle = "page-1"
    chat.target_id = "target-1"
    chat.state = ChatState.BUSY
    chat.set_page_mutation_owner_probe(lambda: False)

    assert await chat.refresh_bound_conversation(request_id="req-terminal") is False
    assert navigated == []
    assert chat._unresolved_recovery_reason == "refresh-owner-not-live"


@pytest.mark.asyncio
async def test_load_failed_replacement_refuses_revoked_owner_before_page_creation() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    runtime = SimpleNamespace(bridge=SimpleNamespace())
    chat = PersistentChat(
        ag_session_id="session-replacement-owner-fence",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url="https://chatgpt.com/g/g-p-project/c/provider-session",
    )
    chat.page_handle = "page-1"
    chat.state = ChatState.RECOVERING
    chat.set_page_mutation_owner_probe(lambda: False)
    chat._conversation_load_recovery_enabled = lambda: True  # type: ignore[method-assign]
    chat._conversation_load_recovery_allowed = lambda: True  # type: ignore[method-assign]
    chat._load_failure_requires_retained_observation = lambda: False  # type: ignore[method-assign]
    chat._prefer_active_conversation_page = lambda: asyncio.sleep(0)  # type: ignore[method-assign]

    created: list[bool] = []

    async def create_page() -> str:
        created.append(True)
        return "replacement-page"

    chat._create_recovery_page = create_page  # type: ignore[method-assign]
    snapshot = ChatSnapshot(
        url="https://chatgpt.com/g/g-p-project/c/provider-session",
        composer_present=False,
        composer_editable=False,
        user_count=1,
        assistant_count=0,
        latest_user_text="prompt",
        latest_assistant_id=None,
        latest_assistant_text=None,
        dom_signals=frozenset({"conversation-load-failed"}),
        error_present=True,
    )

    assert await chat._replace_load_failed_page(snapshot) is False
    assert created == []
    assert chat._unresolved_recovery_reason == "conversation-load-owner-not-live"


@pytest.mark.asyncio
async def test_reconcile_refuses_recovery_page_creation_without_live_owner() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    created: list[bool] = []

    async def find_conversation_page(*_args, **_kwargs):
        return None

    async def create_chat_page():
        created.append(True)
        return "recovery-page"

    runtime = SimpleNamespace(
        bridge=SimpleNamespace(),
        find_conversation_page=find_conversation_page,
        create_chat_page=create_chat_page,
    )
    chat = PersistentChat(
        ag_session_id="session-reconcile-owner-fence",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project/project",
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
        provider_session_id="provider-session",
        chat_url="https://chatgpt.com/g/g-p-project/c/provider-session",
    )
    chat.state = ChatState.RECOVERING
    chat.set_page_mutation_owner_probe(lambda: False)

    await chat.reconcile([])

    assert created == []
    assert chat.page_handle is None
    assert chat._unresolved_recovery_reason == "reconcile-owner-not-live"
