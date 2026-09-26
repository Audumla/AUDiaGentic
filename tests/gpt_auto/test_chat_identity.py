import pytest

from audiagentic.components.providers.adapters.gpt_auto.urls import (
    canonical_chat_url,
    parse_provider_session_id,
    same_chat_identity,
)

BASE = "https://chatgpt.com/g/g-p-69cc8c4cc7648191a009f358113d8dd2"


@pytest.mark.parametrize('temporary', ['local-chatgpt:abc', 'local-chatgpt%3Aabc', 'LOCAL-CHATGPT%3aabc'])
def test_temporary_conversation_is_not_durable_identity(temporary):
    url = BASE + '/c/' + temporary
    assert parse_provider_session_id(url) is None
    assert canonical_chat_url(url) is None


@pytest.mark.parametrize("suffix", ["", "-audiagentic", "-renamed"])
def test_conversation_identity_ignores_display_slug(suffix):
    assert same_chat_identity(BASE + "/c/chat", BASE + suffix + "/c/chat")


@pytest.mark.parametrize("other", [
    BASE + "/c/other",
    "https://chatgpt.com/g/g-p-00000000000000000000000000000000/c/chat",
    "https://evil.example/g/g-p-69cc8c4cc7648191a009f358113d8dd2/c/chat",
    "https://chatgpt.com/c/chat",
    BASE.replace("https:", "http:") + "/c/chat",
])
def test_conversation_identity_rejects_foreign_or_untrusted_routes(other):
    assert not same_chat_identity(BASE + "/c/chat", other)


@pytest.mark.asyncio
async def test_refresh_preserves_observed_slug_and_validates_binding():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat

    page = SimpleNamespace(target_id="target", url=BASE + "-renamed/c/chat")
    browser = SimpleNamespace(page_by_handle=AsyncMock(return_value=page), navigate=AsyncMock())
    chat = object.__new__(PersistentChat)
    chat._page_mutation_lock = asyncio.Lock()
    chat._page_generation = 1
    chat.page_handle = "page"
    chat.target_id = "target"
    chat.provider_session_id = "chat"
    chat.chat_url = BASE + "/c/chat"
    chat._last_snapshot = None
    chat.config = SimpleNamespace(turn=SimpleNamespace(poll_interval_seconds=0))
    chat._gpt_browser = lambda: browser
    token = (1, "page", "target", "chat", chat.chat_url)
    assert await chat.refresh_bound_conversation(expected_binding=token)
    browser.navigate.assert_awaited_once_with(page, page.url)


@pytest.mark.asyncio
@pytest.mark.parametrize('initial_url', [
    'https://chatgpt.com/c/chat', BASE + '/c/local-chatgpt%3Atemporary',
])
async def test_identity_acquisition_waits_for_project_route_after_bare_chat(initial_url):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat

    chat = object.__new__(PersistentChat)
    chat.state = ChatState.BUSY
    chat._recovery_ready = asyncio.Event()
    chat.project_url = BASE
    chat.config = SimpleNamespace(chat=SimpleNamespace(navigation_timeout_seconds=2))
    chat.runtime = SimpleNamespace()
    chat._pending_conversation_title = None
    chat.binding_sink = Mock()
    final = SimpleNamespace(url=BASE + '-title/c/chat', conversation_title=None)
    chat.snapshot = AsyncMock(return_value=final)
    initial = SimpleNamespace(url=initial_url)
    assert await chat.acquire_provider_identity(initial) is final
    assert chat.provider_session_id == 'chat'
    chat.binding_sink.assert_called_once()
    assert chat.state is ChatState.BUSY
