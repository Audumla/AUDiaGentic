import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot
from audiagentic.components.providers.adapters.gpt_auto.tab_leases import TabLeaseStore

URL = 'https://chatgpt.com/g/g-p-project/c/chat'


def test_lease_renewal_failure_does_not_fail_request_or_allow_stale_cleanup():
    runtime = object.__new__(GptAutoProviderRuntime)
    runtime._tab_lease_store = SimpleNamespace(get=lambda _: None, observe=Mock(side_effect=OSError('disk unavailable')))
    runtime._tab_lease_cache = {}
    runtime._tab_lease_unsafe_targets = set()
    chat = SimpleNamespace(target_id='target', ag_session_id='session', chat_url=URL,
        _last_snapshot=ChatSnapshot.from_bridge({'url': URL}),
        _last_validated_activity_monotonic=time.monotonic())
    runtime.remember_tab_activity(chat)
    assert runtime._tab_lease_unsafe_targets == {'target'}
    runtime._tab_lease_store.observe = Mock()
    runtime.remember_tab_activity(chat)
    assert not runtime._tab_lease_unsafe_targets
    runtime.remember_tab_activity(chat)
    runtime._tab_lease_store.observe.assert_called_once()


def test_reattached_session_retains_7190_seconds_of_inactivity(tmp_path, monkeypatch):
    from audiagentic.components.providers.adapters.gpt_auto import runtime as module
    monkeypatch.setattr(module.time, 'time', lambda: 10000.0)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 500.0)
    runtime = object.__new__(GptAutoProviderRuntime)
    runtime._tab_lease_store = TabLeaseStore(tmp_path / 'leases.sqlite3')
    runtime._tab_lease_cache = {}
    runtime._tab_lease_unsafe_targets = set()
    snapshot = ChatSnapshot.from_bridge({'url': URL, 'latestAssistantText': 'done'})
    runtime._tab_lease_store.observe('target', 'session', URL, 2810.0, runtime._tab_digest(snapshot))
    chat = SimpleNamespace(target_id='target', ag_session_id='session', chat_url=URL,
        _last_snapshot=snapshot, _last_validated_activity_monotonic=500.0,
        _validated_activity_generation=0)
    runtime.remember_tab_activity(chat)
    assert 500.0 - chat._last_validated_activity_monotonic == 7190.0
    assert runtime._tab_lease_store.get('target')[3] == 2810.0


def test_lease_store_survives_restart_without_regressing_activity(tmp_path):
    path = tmp_path / 'tabs.sqlite3'
    first = TabLeaseStore(path)
    first.observe('target', 'session', URL, 100, 'digest')
    second = TabLeaseStore(path)
    second.observe('target', 'session', URL, 50, 'new')
    assert second.entries() == [('target', 'session', URL, 100, 'new')]
    second.forget('target')
    assert first.entries() == []
    path.unlink()  # all transaction handles must be closed on Windows


def test_tab_digest_ignores_process_local_dom_observer_state():
    before = ChatSnapshot.from_bridge({
        'url': URL,
        'latestAssistantText': 'answer',
        'domActivityDigest': 'observer-a',
    })
    after_restart = ChatSnapshot.from_bridge({
        'url': URL,
        'latestAssistantText': 'answer',
        'domActivityDigest': 'observer-b',
    })

    assert GptAutoProviderRuntime._tab_digest(before) == GptAutoProviderRuntime._tab_digest(
        after_restart
    )


def test_tab_digest_changes_for_meaningful_conversation_progress():
    before = ChatSnapshot.from_bridge({'url': URL, 'latestAssistantText': 'partial'})
    after = ChatSnapshot.from_bridge({'url': URL, 'latestAssistantText': 'complete'})

    assert GptAutoProviderRuntime._tab_digest(before) != GptAutoProviderRuntime._tab_digest(after)


@pytest.mark.asyncio
@pytest.mark.parametrize('condition', ['idle', 'changed', 'foreign', 'owned', 'absent'])
async def test_restarted_reaper_closes_only_owned_unchanged_idle_target(tmp_path, condition):
    store = TabLeaseStore(tmp_path / 'tabs.sqlite3')
    raw = {'url': URL, 'latestAssistantText': 'answer'}
    digest = GptAutoProviderRuntime._tab_digest(ChatSnapshot.from_bridge(raw))
    store.observe('target', 'session', URL, time.time() - 8000, digest)
    page = SimpleNamespace(target_id='target', handle='new-process-handle',
                           url=URL if condition != 'foreign' else URL + '-different')
    browser = SimpleNamespace(
        pages=AsyncMock(return_value=[] if condition == 'absent' else [page]),
        snapshot=AsyncMock(return_value={**raw, 'latestAssistantText': 'new'} if condition == 'changed' else raw),
        page_by_handle=AsyncMock(return_value=page), close=AsyncMock(),
    )
    runtime = object.__new__(GptAutoProviderRuntime)
    runtime._tab_lease_store = TabLeaseStore(store.path)
    runtime._tab_lease_cache = {}
    runtime._tab_lease_unsafe_targets = set()
    runtime._gpt_browser = browser
    runtime._page_owners = {page.handle: 'session'} if condition == 'owned' else {}
    runtime._detached_tab_closing = set()
    runtime._detached_tab_leases = {}
    runtime.config = SimpleNamespace(workflow=SimpleNamespace(bridge_signals=lambda: []))
    await runtime._reap_durable_tabs(7200)
    if condition == 'idle':
        browser.close.assert_awaited_once_with(page)
    else:
        browser.close.assert_not_awaited()
    if condition == 'changed':
        assert store.entries()[0][3] > time.time() - 5
    assert runtime._detached_tab_closing == set()


@pytest.mark.asyncio
async def test_restarted_reaper_migrates_legacy_digest_without_renewing_idle_clock(tmp_path):
    store = TabLeaseStore(tmp_path / 'tabs.sqlite3')
    raw = {'url': URL, 'latestAssistantText': 'answer'}
    old_activity = time.time() - 8000
    store.observe('target', 'session', URL, old_activity, 'legacy-process-local-digest')
    page = SimpleNamespace(target_id='target', handle='handle', url=URL)
    browser = SimpleNamespace(
        pages=AsyncMock(return_value=[page]),
        snapshot=AsyncMock(return_value=raw),
        page_by_handle=AsyncMock(return_value=page),
        close=AsyncMock(),
    )
    runtime = object.__new__(GptAutoProviderRuntime)
    runtime._tab_lease_store = TabLeaseStore(store.path)
    runtime._tab_lease_cache = {}
    runtime._tab_lease_unsafe_targets = set()
    runtime._gpt_browser = browser
    runtime._page_owners = {}
    runtime._detached_tab_closing = set()
    runtime._detached_tab_leases = {}
    runtime.config = SimpleNamespace(workflow=SimpleNamespace(bridge_signals=lambda: []))

    await runtime._reap_durable_tabs(7200)

    browser.close.assert_awaited_once_with(page)
    assert store.entries() == []
