from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    _active_project_name,
)

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


def test_active_project_name_uses_config_then_directory(tmp_path: Path):
    assert _active_project_name(tmp_path) == tmp_path.name
    config_dir = tmp_path / ".audiagentic" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "project.yaml").write_text("project-name: Big Cherry\n", encoding="utf-8")
    assert _active_project_name(tmp_path) == "Big Cherry"


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
