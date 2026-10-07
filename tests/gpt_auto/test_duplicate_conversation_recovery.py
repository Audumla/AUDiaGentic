from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat


@pytest.mark.asyncio
async def test_load_failure_reuses_healthy_exact_url_duplicate_before_creating_tab() -> None:
    chat = object.__new__(PersistentChat)
    chat.page_handle = "failed-tab"
    chat._conversation_load_recovery_allowed = lambda: True

    async def prefer_healthy_duplicate() -> None:
        chat.page_handle = "healthy-tab"

    chat._prefer_active_conversation_page = prefer_healthy_duplicate
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
    chat.config = SimpleNamespace(
        chat=SimpleNamespace(ready_timeout_seconds=1.0),
        turn=SimpleNamespace(poll_interval_seconds=0.01),
        workflow=SimpleNamespace(recovery=SimpleNamespace(action_pause_seconds=0.01)),
    )
    chat._conversation_load_recovery_allowed = lambda: True
    chat._conversation_load_recovery_attempts = 0
    chat._unresolved_recovery_reason = None
    chat._unresolved_recovery_details = {}
    chat._set_unresolved_recovery = PersistentChat._set_unresolved_recovery.__get__(chat)
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
