from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.project.project_api import resolve_project_name
from audiagentic.components.providers.adapters.gpt_auto import session_transport
from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig

from .test_greenfield_config_urls import valid_config


class _Bridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method, params=None, **kwargs):
        params = params or {}
        self.calls.append((method, params))
        if method == "list_pages":
            return []
        if method in {"create_page", "create_window_page"}:
            return {"pageHandle": "page-1"}
        if method == "find_project_url":
            assert params["projectName"] == "bigcherry"
            return {
                "url": "https://chatgpt.com/g/g-p-bigcherry/project",
                "name": "bigcherry",
            }
        return {"ok": True}


class _Runtime:
    def __init__(self) -> None:
        self.bridge = _Bridge()
        self.config = SimpleNamespace(
            browser=SimpleNamespace(dedicated_window=False),
            chat=SimpleNamespace(
                navigation_timeout_seconds=1,
                ready_timeout_seconds=1,
            ),
        )

    async def ensure_available(self) -> None:
        return None

    async def register_chat(self, chat) -> None:
        return None

    def unregister_chat(self, chat) -> None:
        return None

    def release_page(self, chat, page_handle) -> None:
        return None

    def claim_page(self, chat, page_handle) -> bool:
        return True


@pytest.mark.asyncio
async def test_initial_chat_discovers_project_by_active_project_name(monkeypatch):
    runtime = _Runtime()
    chat = PersistentChat(
        ag_session_id="session-1",
        project_name="bigcherry",
        project_url=None,
        runtime=runtime,
        config=GptAutoConfig.from_dict(valid_config()),
        binding_sink=lambda update: None,
    )

    async def ready() -> None:
        return None

    async def snapshot(*, allow_recovering=False):
        return SimpleNamespace(url=chat.project_url)

    monkeypatch.setattr(chat, "_wait_ready", ready)
    monkeypatch.setattr(chat, "snapshot", snapshot)
    await chat.open()

    assert chat.project_url == "https://chatgpt.com/g/g-p-bigcherry/project"
    methods = [method for method, _ in runtime.bridge.calls]
    assert methods == [
        "create_page",
        "navigate",
        "find_project_url",
        "navigate",
    ]
    assert runtime.bridge.calls[1][1]["url"] == "https://chatgpt.com/projects"
    assert runtime.bridge.calls[3][1]["url"] == chat.project_url


def test_project_name_uses_workspace_then_config_then_directory(tmp_path: Path):
    assert resolve_project_name(tmp_path) == tmp_path.name
    config_dir = tmp_path / ".audiagentic" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "project.yaml").write_text("project-name: Big Cherry\n", encoding="utf-8")
    assert resolve_project_name(tmp_path) == "Big Cherry"
    assert resolve_project_name(tmp_path, workspace_name="Workspace Name") == "Workspace Name"


def test_session_transport_uses_admitted_project_name(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    class FakeChat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(session_transport, "PersistentChat", FakeChat)
    monkeypatch.setattr(session_transport, "get_runtime", lambda *_args: object())

    session_transport.build_session_transport(
        tmp_path,
        config=valid_config(),
        ag_session_id="session-1",
        binding_sink=lambda _update: None,
        project_name="Workspace Name",
    )

    assert captured["project_name"] == "Workspace Name"


@pytest.mark.asyncio
async def test_page_lost_does_not_reconcile_immediately_when_idle():
    """GP12: closing an idle chat's tab must not force an immediate
    recreate-and-navigate -- that leaves the user unable to ever actually
    close it. Recovery should wait for the existing lazy
    ensure_ready() -> reconcile() path on next real use, exactly like
    GptAutoProviderRuntime.recover() already does for idle chats."""
    runtime = _Runtime()
    chat = PersistentChat(
        ag_session_id="session-1",
        project_name="bigcherry",
        project_url="https://chatgpt.com/g/g-p-bigcherry/project",
        runtime=runtime,
        config=GptAutoConfig.from_dict(valid_config()),
        binding_sink=lambda update: None,
        provider_session_id="conv-1",
        chat_url="https://chatgpt.com/g/g-p-bigcherry/c/conv-1",
    )
    chat.state = ChatState.READY
    chat.page_handle = "page-1"
    chat.active_turn_id = None

    await chat.page_lost("page-1")

    assert chat.state is ChatState.RECOVERING
    assert chat.page_handle is None
    assert runtime.bridge.calls == []


@pytest.mark.asyncio
async def test_page_lost_reconciles_immediately_when_turn_active():
    """A turn actively in flight when its page is lost still needs eager
    reconciliation -- only idle chats get the lazy path."""
    runtime = _Runtime()
    chat = PersistentChat(
        ag_session_id="session-1",
        project_name="bigcherry",
        project_url="https://chatgpt.com/g/g-p-bigcherry/project",
        runtime=runtime,
        config=GptAutoConfig.from_dict(valid_config()),
        binding_sink=lambda update: None,
        provider_session_id="conv-1",
        chat_url="https://chatgpt.com/g/g-p-bigcherry/c/conv-1",
    )
    chat.state = ChatState.BUSY
    chat.page_handle = "page-1"
    chat.active_turn_id = "req-1"

    async def ready() -> None:
        return None

    async def wait_quiescent(*, allow_recovering=False):
        return None

    chat._wait_ready = ready  # type: ignore[method-assign]
    chat.wait_quiescent = wait_quiescent  # type: ignore[method-assign]

    await chat.page_lost("page-1")

    methods = [method for method, _ in runtime.bridge.calls]
    assert "list_pages" in methods
    assert chat.state is ChatState.BUSY


@pytest.mark.asyncio
async def test_deleted_provider_conversation_is_not_reopened_from_project_redirect(monkeypatch):
    """A deleted chat URL may redirect to its project workspace.

    The workspace is not the durable conversation. Recovery must close the
    temporary tab, terminalize the chat, and surface the explicit missing-chat
    error rather than reopening the same project tab indefinitely.
    """
    runtime = _Runtime()
    chat = PersistentChat(
        ag_session_id="session-deleted-chat",
        project_name="bigcherry",
        project_url="https://chatgpt.com/g/g-p-bigcherry/project",
        runtime=runtime,
        config=GptAutoConfig.from_dict(valid_config()),
        binding_sink=lambda update: None,
        provider_session_id="deleted-conversation",
        chat_url="https://chatgpt.com/g/g-p-bigcherry/c/deleted-conversation",
    )
    chat.state = ChatState.RECOVERING

    async def wait_ready():
        return SimpleNamespace(url=chat.project_url)

    monkeypatch.setattr(chat, "_wait_ready", wait_ready)
    await chat.reconcile([])

    assert chat.state is ChatState.FAILED
    assert chat.page_handle is None
    assert [method for method, _ in runtime.bridge.calls] == ["create_page", "navigate", "close_page"]

    with pytest.raises(Exception) as exc_info:
        await chat.ensure_ready()
    assert getattr(exc_info.value, "code", None) == "EXT-GPTAUTO-005"
