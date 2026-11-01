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
    assert runtime.bridge.calls[1][1]["url"] == "https://chatgpt.com/"
    assert runtime.bridge.calls[3][1]["url"] == chat.project_url


def test_project_name_uses_config_then_workspace_then_directory(tmp_path: Path):
    assert resolve_project_name(tmp_path) == tmp_path.name
    assert resolve_project_name(tmp_path, workspace_name="Workspace Name") == "Workspace Name"
    settings_dir = tmp_path / ".audiagentic"
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.yaml").write_text("schema_version: 1\nproject:\n  name: Big Cherry\n", encoding="utf-8")
    assert resolve_project_name(tmp_path) == "Big Cherry"
    assert resolve_project_name(tmp_path, workspace_name="bigcherry") == "Big Cherry"


def test_project_name_uses_git_repository_name_across_worktrees(tmp_path: Path):
    main = tmp_path / "checkout-dir"
    common = main / ".git"
    (common / "worktrees" / "wt-feature").mkdir(parents=True)
    (common / "config").write_text(
        '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/Owner/RepoName.git\n'
        '\tfetch = +refs/heads/*:refs/remotes/origin/*\n',
        encoding="utf-8",
    )
    worktree = tmp_path / "wt-feature"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {common / 'worktrees' / 'wt-feature'}\n", encoding="utf-8")
    (common / "worktrees" / "wt-feature" / "commondir").write_text("../..\n", encoding="utf-8")

    assert resolve_project_name(main) == "RepoName"
    assert resolve_project_name(worktree) == "RepoName"
    assert resolve_project_name(worktree, workspace_name="Label") == "Label"

    # Without an origin remote, the main checkout's directory names the repository.
    (common / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    assert resolve_project_name(worktree) == "checkout-dir"

    # SSH remotes name the repository too.
    (common / "config").write_text('[remote "origin"]\n\turl = git@github.com:Owner/Other.git\n', encoding="utf-8")
    assert resolve_project_name(worktree) == "Other"


def test_session_transport_uses_admitted_project_name(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    class FakeChat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def set_page_mutation_owner_probe(self, _probe):
            return None

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


def test_session_transport_uses_provider_project_name_for_pinned_profile(
    monkeypatch, tmp_path: Path
):
    captured: dict[str, object] = {}

    class FakeChat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def set_page_mutation_owner_probe(self, _probe):
            return None

    monkeypatch.setattr(session_transport, "PersistentChat", FakeChat)
    monkeypatch.setattr(session_transport, "get_runtime", lambda *_args: object())
    config = valid_config()
    config["project-name"] = "gpt-t2"
    config["project-url"] = (
        "https://chatgpt.com/g/g-p-00000000000000009a68838cfbc78e31/project"
    )

    session_transport.build_session_transport(
        tmp_path,
        config=config,
        ag_session_id="session-1",
        binding_sink=lambda _update: None,
        project_name="AUDiaGentic",
    )

    assert captured["project_name"] == "gpt-t2"


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
    # The in-flight turn's page is gone: the chat stays RECOVERING with its owned checkpoint until the
    # conversation is re-proven (it is not returned to BUSY by an eager reconcile alone).
    assert chat.state is ChatState.RECOVERING


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
