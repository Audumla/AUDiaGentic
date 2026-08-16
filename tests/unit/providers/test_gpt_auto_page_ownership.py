from __future__ import annotations

from types import SimpleNamespace

from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime


def _runtime() -> GptAutoProviderRuntime:
    runtime = object.__new__(GptAutoProviderRuntime)
    runtime._page_owners = {}
    runtime._chats = {}
    return runtime


def test_gpt_auto_page_claim_is_exclusive_per_live_session() -> None:
    runtime = _runtime()
    first = SimpleNamespace(ag_session_id="session-a")
    second = SimpleNamespace(ag_session_id="session-b")

    assert runtime.claim_page(first, "page-1") is True
    assert runtime.claim_page(second, "page-1") is False
    assert runtime.claim_page(first, "page-1") is True


def test_gpt_auto_page_release_allows_next_session_to_claim() -> None:
    runtime = _runtime()
    first = SimpleNamespace(ag_session_id="session-a")
    second = SimpleNamespace(ag_session_id="session-b")

    assert runtime.claim_page(first, "page-1") is True
    runtime.release_page(first, "page-1")
    assert runtime.claim_page(second, "page-1") is True


def test_unregister_chat_releases_owned_page() -> None:
    runtime = _runtime()
    chat = SimpleNamespace(ag_session_id="session-a", page_handle="page-1", provider_session_id=None)
    runtime._chats[chat.ag_session_id] = chat
    assert runtime.claim_page(chat, chat.page_handle) is True

    runtime.unregister_chat(chat)

    assert "session-a" not in runtime._chats
    assert runtime._page_owners == {}
