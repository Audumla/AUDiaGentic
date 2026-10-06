from __future__ import annotations

from types import SimpleNamespace

from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime


def _runtime() -> GptAutoProviderRuntime:
    runtime = object.__new__(GptAutoProviderRuntime)
    runtime._page_owners = {}
    runtime._detached_tab_closing = set()
    runtime._detached_tab_leases = {}
    runtime._chats = {}
    return runtime


def test_gpt_auto_page_claim_is_exclusive_per_live_session() -> None:
    runtime = _runtime()
    first = SimpleNamespace(ag_session_id="session-a")
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
    first.state = ChatState.READY
    runtime._chats[first.ag_session_id] = first
    second = SimpleNamespace(ag_session_id="session-b")
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState
    second.state = ChatState.READY
    runtime._chats[second.ag_session_id] = second

    assert runtime.claim_page(first, "page-1") is True
    assert runtime.claim_page(second, "page-1") is False
    assert runtime.claim_page(first, "page-1") is True


def test_gpt_auto_page_claim_reclaims_terminal_prior_chat() -> None:
    runtime = _runtime()
    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState

    prior = SimpleNamespace(
        ag_session_id="session-a", state=ChatState.CLOSED
    )
    current = SimpleNamespace(ag_session_id="session-b")
    runtime._chats[prior.ag_session_id] = prior
    runtime._page_owners["page-1"] = prior.ag_session_id

    assert runtime.claim_page(current, "page-1") is True
    assert runtime._page_owners["page-1"] == current.ag_session_id

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
