from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.providers.adapters.gpt_auto.browser_process import (
    BrowserProcessController,
)
from audiagentic.components.providers.adapters.gpt_auto.chat import ChatState, PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime
from audiagentic.components.providers.adapters.gpt_auto.runtime_registry import (
    _runtimes,
    get_runtime,
    shutdown_all_runtimes,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_greenfield_config_urls import valid_config


@pytest.mark.asyncio
async def test_browser_reuses_connectable_cdp_without_process_mutation():
    config = GptAutoConfig.from_dict(valid_config()).browser
    lookups = []
    controller = BrowserProcessController(
        config,
        cdp_probe=lambda: _true(),
        process_lookup=lambda path: lookups.append(path) or [],
        port_owner=lambda port: 42,
    )
    evidence = await controller.ensure_browser_for_cdp()
    assert evidence.pid == 42
    assert not evidence.launched_by_provider
    assert lookups == []


@pytest.mark.asyncio
async def test_unknown_process_on_cdp_port_fails_without_kill():
    config = GptAutoConfig.from_dict(valid_config()).browser
    controller = BrowserProcessController(
        config,
        cdp_probe=lambda: _false(),
        process_lookup=lambda path: [],
        port_owner=lambda port: 777,
    )
    with pytest.raises(RuntimeError, match="occupied"):
        await controller.ensure_browser_for_cdp()


@pytest.mark.asyncio
async def test_running_configured_browser_fail_policy_does_not_terminate():
    config = GptAutoConfig.from_dict(valid_config()).browser
    controller = BrowserProcessController(
        config,
        cdp_probe=lambda: _false(),
        process_lookup=lambda path: [123],
        port_owner=lambda port: None,
    )
    with pytest.raises(RuntimeError, match="running without usable CDP"):
        await controller.ensure_browser_for_cdp()


@pytest.mark.asyncio
async def test_restart_policy_refuses_unowned_browser_process():
    value = valid_config()
    value["browser"]["existing-browser-policy"] = "restart"
    config = GptAutoConfig.from_dict(value).browser
    controller = BrowserProcessController(
        config,
        cdp_probe=lambda: _false(),
        process_lookup=lambda path: [123],
        port_owner=lambda port: None,
    )
    with pytest.raises(RuntimeError, match="ownership cannot be proven"):
        await controller.ensure_browser_for_cdp()


def test_runtime_registry_shares_machine_runtime_but_allows_project_turn_policy(tmp_path):
    _runtimes.clear()
    config = GptAutoConfig.from_dict(valid_config())
    assert get_runtime(tmp_path, config) is get_runtime(tmp_path, config)
    changed = valid_config()
    changed["turn"]["poll-interval-seconds"] = 2
    assert get_runtime(tmp_path, GptAutoConfig.from_dict(changed)) is get_runtime(tmp_path, config)
    changed["cdp"]["protocol-timeout-seconds"] = 31
    with pytest.raises(RuntimeError, match="machine runtime configuration"):
        get_runtime(tmp_path, GptAutoConfig.from_dict(changed))
    _runtimes.clear()


def test_delayed_binding_is_idempotent_and_conflict_fails(tmp_path: Path):
    record = sessions_store.build_session_record(
        session_id="ses-lazy-binding",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        surface_id="gpt-auto-cdp",
        provider_session_ref=None,
    )
    sessions_store.write_session_record(tmp_path, record)
    kwargs = {
        "provider_id": "gpt-auto",
        "surface_id": "gpt-auto-cdp",
        "provider_session_ref": "conversation-1",
        "metadata": {"chat-url": "https://chatgpt.com/g/g-p-project/c/conversation-1"},
    }
    first = sessions_store.install_initial_provider_binding(tmp_path, "ses-lazy-binding", **kwargs)
    second = sessions_store.install_initial_provider_binding(tmp_path, "ses-lazy-binding", **kwargs)
    assert first["binding"]["binding-id"] == second["binding"]["binding-id"]
    with pytest.raises(AudiaGenticError) as raised:
        sessions_store.install_initial_provider_binding(
            tmp_path,
            "ses-lazy-binding",
            **{**kwargs, "provider_session_ref": "conversation-2"},
        )
    assert raised.value.code == "CON-AGW-120"


@pytest.mark.asyncio
async def test_runtime_shutdown_reports_failures_on_supported_python_versions():
    """Cleanup failures must not turn into a Python-3.10 ExceptionGroup NameError."""

    class _BrokenRuntime:
        async def shutdown_from_owner(self):
            raise OSError("browser still attached")

    _runtimes.clear()
    _runtimes[("browser", 9222, "http://127.0.0.1:9222")] = _BrokenRuntime()
    with pytest.raises(RuntimeError, match="runtime shutdown failed .*OSError"):
        await shutdown_all_runtimes()
    # Failed entries remain registered for a later retry.
    assert _runtimes
    _runtimes.clear()


class _IdleTabBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict):
        self.calls.append((method, params))
        return {"ok": True}


class _IdleTabRuntime:
    def __init__(self, bridge: _IdleTabBridge) -> None:
        self.bridge = bridge
        self.released: list[str] = []

    def release_page(self, _chat, handle: str | None) -> None:
        if handle:
            self.released.append(handle)

    def unregister_chat(self, _chat) -> None:
        return None


def _idle_chat(runtime: _IdleTabRuntime) -> PersistentChat:
    chat = PersistentChat(
        ag_session_id="ses-idle",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project",
        runtime=runtime,  # type: ignore[arg-type]
        config=GptAutoConfig.from_dict(valid_config()),
        binding_sink=lambda _update: None,
        provider_session_id="conversation-1",
        chat_url="https://chatgpt.com/g/g-p-project/c/conversation-1",
    )
    chat.page_handle = "page-1"
    chat.target_id = "target-1"
    chat.state = ChatState.READY
    chat._last_validated_activity_monotonic = 100.0
    return chat


@pytest.mark.asyncio
async def test_idle_tab_reaper_closes_physical_page_but_preserves_session_binding() -> None:
    bridge = _IdleTabBridge()
    runtime = _IdleTabRuntime(bridge)
    chat = _idle_chat(runtime)

    reclaimed = await chat.close_physical_page_if_idle(now=7_301.0, idle_timeout_seconds=7_200.0)

    assert reclaimed is True
    assert bridge.calls == [("close_page", {"pageHandle": "page-1"})]
    assert runtime.released == ["page-1"]
    assert chat.page_handle is None
    assert chat.target_id is None
    assert chat.provider_session_id == "conversation-1"
    assert chat.chat_url == "https://chatgpt.com/g/g-p-project/c/conversation-1"
    assert chat.state is ChatState.READY


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["active", "pending", "recent"])
async def test_idle_tab_reaper_never_closes_ineligible_page(guard: str) -> None:
    bridge = _IdleTabBridge()
    runtime = _IdleTabRuntime(bridge)
    chat = _idle_chat(runtime)
    if guard == "active":
        chat.active_turn_id = "req-1"
    elif guard == "pending":
        chat.pending_turns = 1
    elif guard == "recent":
        chat._last_validated_activity_monotonic = 7_000.0

    reclaimed = await chat.close_physical_page_if_idle(now=7_301.0, idle_timeout_seconds=7_200.0)

    assert reclaimed is False
    assert bridge.calls == []
    assert chat.page_handle == "page-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [ChatState.BUSY, ChatState.RECOVERING, ChatState.FAILED])
async def test_idle_tab_reaper_ignores_failure_state_when_session_is_stale(
    state: ChatState,
) -> None:
    bridge = _IdleTabBridge()
    runtime = _IdleTabRuntime(bridge)
    chat = _idle_chat(runtime)
    chat.state = state
    chat.unresolved_turn_pending = True

    reclaimed = await chat.close_physical_page_if_idle(now=7_301.0, idle_timeout_seconds=7_200.0)

    assert reclaimed is True
    assert bridge.calls == [("close_page", {"pageHandle": "page-1"})]


@pytest.mark.asyncio
async def test_closed_session_tab_is_retained_for_independent_idle_reaping() -> None:
    bridge = _IdleTabBridge()
    config = GptAutoConfig.from_dict(valid_config())
    runtime = _IdleTabRuntime(bridge)
    runtime.config = config
    runtime.retained = []
    runtime.retain_detached_page = lambda _chat, handle, last: runtime.retained.append((handle, last))
    chat = PersistentChat(
        ag_session_id="ses-detached",
        project_name="project",
        project_url="https://chatgpt.com/g/g-p-project",
        runtime=runtime,  # type: ignore[arg-type]
        config=config,
        binding_sink=lambda _update: None,
    )
    chat.page_handle = "page-detached"
    chat.state = ChatState.READY
    chat._last_validated_activity_monotonic = 100.0

    await chat.close()

    assert runtime.retained == [("page-detached", 100.0)]
    assert bridge.calls == []


@pytest.mark.asyncio
async def test_runtime_idle_sweep_uses_configured_interval_and_threshold() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    config = replace(
        config,
        browser=replace(
            config.browser,
            physical_tab_reaper_interval_seconds=0.001,
            physical_tab_idle_timeout_seconds=17.0,
        ),
    )
    runtime = GptAutoProviderRuntime(config)
    bridge = object()
    runtime._bridge = bridge  # type: ignore[assignment]
    calls: list[tuple[float, float]] = []

    class Chat:
        ag_session_id = "ses-sweep"

        async def close_physical_page_if_idle(self, *, now: float, idle_timeout_seconds: float) -> bool:
            calls.append((now, idle_timeout_seconds))
            return False

    runtime._chats["ses-sweep"] = Chat()  # type: ignore[assignment]
    task = asyncio.create_task(runtime._reap_idle_tabs(bridge))  # type: ignore[arg-type]
    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert calls
    assert all(timeout == 17.0 for _now, timeout in calls)


@pytest.mark.asyncio
async def test_runtime_idle_sweep_reaps_detached_retained_tab() -> None:
    config = GptAutoConfig.from_dict(valid_config())
    config = replace(
        config,
        browser=replace(
            config.browser,
            physical_tab_reaper_interval_seconds=0.001,
            physical_tab_idle_timeout_seconds=17.0,
        ),
    )
    runtime = GptAutoProviderRuntime(config)
    bridge = _IdleTabBridge()
    runtime._bridge = bridge  # type: ignore[assignment]
    runtime.retain_detached_page(SimpleNamespace(ag_session_id="ses-detached"), "page-1", 100.0)

    task = asyncio.create_task(runtime._reap_idle_tabs(bridge))
    try:
        await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert bridge.calls == [("close_page", {"pageHandle": "page-1"})]
    assert runtime._detached_tab_leases == {}


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False
