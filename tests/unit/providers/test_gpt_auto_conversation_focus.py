import asyncio

from audiagentic.components.providers.adapters.gpt_auto import conversation_focus
from audiagentic.components.providers.adapters.gpt_auto.conversation_focus import select_focus_page
from audiagentic.components.providers.contracts import ConversationFocusLocator


def _locator(url=None, session=None):
    return ConversationFocusLocator(chat_url=url, provider_session_id=session)


def test_focus_selects_exact_url_and_session():
    page = {"type": "page", "pageHandle": "h1", "url": "https://chatgpt.com/g/g-p-x/c/s1"}
    selected, result = select_focus_page([page], _locator(page["url"], "s1"))
    assert selected is page
    assert result is None


def test_focus_uses_unique_session_when_url_is_stale():
    page = {"type": "page", "pageHandle": "h1", "url": "https://chatgpt.com/g/g-p-x/c/s1"}
    selected, result = select_focus_page([page], _locator("https://chatgpt.com/g/g-p-x/c/old", "s1"))
    assert selected is page
    assert result is None


def test_focus_rejects_conflicting_url_and_session():
    first = {"type": "page", "pageHandle": "h1", "url": "https://chatgpt.com/g/g-p-x/c/s1"}
    second = {"type": "page", "pageHandle": "h2", "url": "https://chatgpt.com/g/g-p-x/c/s2"}
    selected, result = select_focus_page([first, second], _locator(first["url"], "s2"))
    assert selected is None
    assert result is not None
    assert result.outcome.value == "identity-conflict"


def test_focus_rejects_duplicate_session():
    pages = [
        {"type": "page", "pageHandle": "h1", "url": "https://chatgpt.com/g/g-p-x/c/s1"},
        {"type": "page", "pageHandle": "h2", "url": "https://chatgpt.com/g/g-p-y/c/s1"},
    ]
    selected, result = select_focus_page(pages, _locator(session="s1"))
    assert selected is None
    assert result is not None
    assert result.outcome.value == "ambiguous"


def test_focus_scopes_session_identity_to_admitted_project():
    pages = [
        {"type": "page", "pageHandle": "h1", "url": "https://chatgpt.com/g/g-p-x/c/s1"},
        {"type": "page", "pageHandle": "h2", "url": "https://chatgpt.com/g/g-p-y/c/s1"},
    ]
    selected, result = select_focus_page(
        pages,
        ConversationFocusLocator(provider_session_id="s1", project_url="https://chatgpt.com/g/g-p-y"),
    )
    assert selected is pages[1]
    assert result is None


def test_focus_repairs_stale_project_url_from_durable_chat_url():
    chat = "https://chatgpt.com/g/g-p-target/c/s1"
    selected, result = select_focus_page(
        [{"type": "page", "pageHandle": "h1", "url": chat}],
        ConversationFocusLocator(
            chat_url=chat,
            provider_session_id="s1",
            project_url="https://chatgpt.com/g/g-p-stale/project",
        ),
    )
    assert selected is not None
    assert selected["pageHandle"] == "h1"
    assert result is None


def test_focus_existing_conversation_activates_target_before_renderer_focus(monkeypatch, tmp_path):
    calls = []

    class FakeBridge:
        async def call(self, method, params=None):
            calls.append((method, params))
            if method == "list_pages":
                return [{"type": "page", "pageHandle": "h1", "url": "https://chatgpt.com/g/g-p-x/c/s1"}]
            return {"ok": True}

    class FakeRuntime:
        bridge = FakeBridge()

        async def connect_existing(self):
            return True

        def adopt_existing_dedicated_window(self, pages):
            return None

        def page_belongs_to_dedicated_window(self, page):
            return True

    monkeypatch.setattr(
        conversation_focus,
        "load_provider_config",
        lambda project_root: {"providers": {"gpt-auto": {}}},
    )
    monkeypatch.setattr(conversation_focus, "get_runtime", lambda project_root, config: FakeRuntime())

    result = asyncio.run(
        conversation_focus.focus_existing_conversation(
            tmp_path,
            provider_id="gpt-auto",
            locator=_locator("https://chatgpt.com/g/g-p-x/c/s1", "s1"),
        )
    )

    assert result.outcome.value == "focused"
    assert [method for method, _ in calls] == ["list_pages", "activate_target", "keep_page_active"]
    assert calls[1][1] == {"pageHandle": "h1"}


def test_focus_existing_conversation_falls_back_to_other_window(monkeypatch, tmp_path):
    calls = []

    class FakeBridge:
        async def call(self, method, params=None):
            calls.append((method, params))
            if method == "list_pages":
                return [{"type": "page", "pageHandle": "h2", "url": "https://chatgpt.com/g/g-p-x/c/s2"}]
            return {"ok": True}

    class FakeRuntime:
        bridge = FakeBridge()

        async def connect_existing(self):
            return True

        def adopt_existing_dedicated_window(self, pages):
            return None

        def page_belongs_to_dedicated_window(self, page):
            return False

    monkeypatch.setattr(
        conversation_focus,
        "load_provider_config",
        lambda project_root: {"providers": {"gpt-auto": {}}},
    )
    monkeypatch.setattr(conversation_focus, "get_runtime", lambda project_root, config: FakeRuntime())

    result = asyncio.run(
        conversation_focus.focus_existing_conversation(
            tmp_path,
            provider_id="gpt-auto",
            locator=_locator("https://chatgpt.com/g/g-p-x/c/s2", "s2"),
        )
    )

    assert result.outcome.value == "focused"
    assert [method for method, _ in calls] == [
        "list_pages",
        "activate_target",
        "keep_page_active",
    ]
