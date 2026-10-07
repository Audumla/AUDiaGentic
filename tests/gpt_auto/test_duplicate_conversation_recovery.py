from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat


@pytest.mark.asyncio
async def test_load_failure_reuses_healthy_exact_url_duplicate_before_creating_tab() -> None:
    chat = object.__new__(PersistentChat)
    chat.page_handle = "failed-tab"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    chat.provider_session_id = None
    chat._conversation_load_recovery_allowed = lambda: True
    chat.config = SimpleNamespace(
        chat=SimpleNamespace(ready_timeout_seconds=1.0),
        turn=SimpleNamespace(poll_interval_seconds=0.01),
        workflow=SimpleNamespace(recovery=SimpleNamespace(conversation_load_failure_recovery_enabled=True, action_pause_seconds=0.01)),
    )

    async def prefer_healthy_duplicate() -> None:
        chat.page_handle = "healthy-tab"

    chat._prefer_active_conversation_page = prefer_healthy_duplicate
    chat._replacement_snapshot_is_positive = lambda _snapshot: True
    chat._reset_load_recovery_budget_after_positive_snapshot = AsyncMock()
    chat.snapshot = AsyncMock(
        return_value=SimpleNamespace(dom_signals=frozenset({"response-complete"}))
    )
    chat._create_recovery_page = AsyncMock(
        side_effect=AssertionError("a healthy exact-URL duplicate must be reused")
    )

    recovered = await PersistentChat._replace_load_failed_page(
        chat,
        SimpleNamespace(dom_signals=frozenset({"conversation-load-failed"})),
    )

    assert recovered is True
    assert chat.page_handle == "healthy-tab"
    chat.snapshot.assert_awaited_once_with(allow_recovering=True)
    chat._create_recovery_page.assert_not_awaited()
@pytest.mark.asyncio
async def test_load_failure_retries_retained_tab_before_replacement() -> None:
    chat = object.__new__(PersistentChat)
    chat.page_handle = "failed-tab"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    chat.config = SimpleNamespace(
        chat=SimpleNamespace(ready_timeout_seconds=1.0),
        turn=SimpleNamespace(poll_interval_seconds=0.01),
        workflow=SimpleNamespace(recovery=SimpleNamespace(action_pause_seconds=0.01)),
    )
    chat._conversation_load_recovery_allowed = lambda: True
    chat._conversation_load_recovery_attempts = 0
    chat.unresolved_turn_pending = False
    chat._defer_unresolved_reconciliation = False
    chat._unresolved_recovery_reason = None
    chat._unresolved_recovery_details = {}
    chat._checkpoint_metadata = {}
    chat._submission_proven = False
    chat.target_id = None
    chat.unresolved_prompt_message_id = None
    chat.unresolved_assistant_message_id = None
    chat.unresolved_assistant_before_id = None
    chat.unresolved_prompt_text_digest = None
    chat._persist_checkpoint = AsyncMock()
    chat._set_unresolved_recovery = PersistentChat._set_unresolved_recovery.__get__(chat)
    chat._replacement_snapshot_is_positive = lambda _snapshot: True
    chat._prefer_active_conversation_page = AsyncMock()
    chat.retry_conversation_load = AsyncMock(return_value=True)
    chat.snapshot = AsyncMock(
        return_value=SimpleNamespace(dom_signals=frozenset())
    )
    chat._create_recovery_page = AsyncMock(
        side_effect=AssertionError("same-tab Retry should precede replacement creation")
    )

    recovered = await PersistentChat._replace_load_failed_page(
        chat,
        SimpleNamespace(dom_signals=frozenset({"conversation-load-failed"})),
    )

    assert recovered is True
    chat.retry_conversation_load.assert_awaited_once()
    chat._create_recovery_page.assert_not_awaited()
    assert chat._unresolved_recovery_reason == "conversation-load-retry-recovered"
@pytest.mark.asyncio
async def test_unproven_duplicate_restores_failed_page_before_retry() -> None:
    chat = object.__new__(PersistentChat)
    chat.page_handle = "failed-tab"
    chat.chat_url = "https://chatgpt.com/g/g-p-project/c/provider-session"
    chat.provider_session_id = None
    chat.config = SimpleNamespace(
        chat=SimpleNamespace(ready_timeout_seconds=1.0),
        turn=SimpleNamespace(poll_interval_seconds=0.01),
        workflow=SimpleNamespace(recovery=SimpleNamespace(action_pause_seconds=0.01)),
    )
    chat.runtime = SimpleNamespace(
        claim_page=lambda _chat, _handle: True,
        release_page=lambda _chat, _handle: None,
    )
    chat._conversation_load_recovery_allowed = lambda: False
    chat._conversation_load_recovery_attempts = 0
    chat._prefer_active_conversation_page = AsyncMock(
        side_effect=lambda: setattr(chat, "page_handle", "blank-duplicate")
    )
    chat.snapshot = AsyncMock(
        return_value=SimpleNamespace(dom_signals=frozenset())
    )
    chat._replacement_snapshot_is_positive = lambda _snapshot: False
    chat.retry_conversation_load = AsyncMock(return_value=False)
    chat._unresolved_recovery_reason = None
    chat._unresolved_recovery_details = {}
    chat._set_unresolved_recovery = PersistentChat._set_unresolved_recovery.__get__(chat)

    recovered = await PersistentChat._replace_load_failed_page(
        chat,
        SimpleNamespace(dom_signals=frozenset({"conversation-load-failed"})),
    )

    assert recovered is False
    assert chat.page_handle == "failed-tab"
    chat.retry_conversation_load.assert_awaited_once()
