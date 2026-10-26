from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import async_playwright

from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat

from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
    GptAutoCdpBrowserController, _RETRY_CONVERSATION_LOAD_FN, _SNAPSHOT_FN,
)
from audiagentic.components.providers.adapters.gpt_auto.cdp.cdp_browser import CdpPageRef

URL = 'https://chatgpt.com/g/g-p-test/c/conversation'
ERROR = '<div id="main-frame-error"><div class="error-code">DNS_PROBE_FINISHED_NO_INTERNET</div></div>'


@pytest.mark.asyncio
async def test_native_network_page_recovers_same_background_tab():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            loads = []

            async def serve(route):
                loads.append(route.request.url)
                await route.fulfill(body=ERROR if len(loads) == 1 else '<textarea>ready</textarea>', content_type='text/html')

            await page.route('**/*', serve)
            await page.goto(URL)
            foreground = await context.new_page()
            await foreground.bring_to_front()
            snapshot = await page.evaluate(_SNAPSHOT_FN, [])
            assert snapshot['domSignals']['browser-network-error']
            assert snapshot['domSignals']['conversation-load-failed']
            assert snapshot['errorPresent']
            assert await page.evaluate(_RETRY_CONVERSATION_LOAD_FN, {'expectedPath': '/g/g-p-test/c/conversation'})
            await page.wait_for_selector('textarea')
            assert loads == [URL, URL]
            assert len(browser.contexts[0].pages) == 2
            assert not (await page.evaluate(_SNAPSHOT_FN, []))['domSignals'].get('browser-network-error')
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_persistent_network_error_does_not_create_replacement_tabs(monkeypatch):
    clock = 0.0

    async def advance(seconds):
        nonlocal clock
        clock += seconds

    monkeypatch.setattr(asyncio.get_running_loop(), 'time', lambda: clock)
    monkeypatch.setattr(asyncio, 'sleep', advance)
    chat = object.__new__(PersistentChat)
    chat.page_handle = 'retained'
    chat.chat_url = URL
    chat.active_turn_id = None
    chat.unresolved_turn_pending = False
    chat.config = SimpleNamespace(
        chat=SimpleNamespace(ready_timeout_seconds=2.0),
        turn=SimpleNamespace(poll_interval_seconds=0.01),
        workflow=SimpleNamespace(recovery=SimpleNamespace(
            conversation_load_failure_recovery_enabled=True, action_pause_seconds=0)),
    )
    chat.retry_conversation_load = AsyncMock(return_value=True)
    chat._prefer_active_conversation_page = AsyncMock()
    chat._create_recovery_page = AsyncMock()
    error = SimpleNamespace(dom_signals=frozenset({'browser-network-error', 'conversation-load-failed'}))
    chat.snapshot = AsyncMock(return_value=error)
    assert not await chat._replace_load_failed_page(error)
    assert chat.retry_conversation_load.await_count == 3
    assert chat.snapshot.await_count == 2
    assert clock == 2.0
    chat._prefer_active_conversation_page.assert_not_awaited()
    chat._create_recovery_page.assert_not_awaited()
    assert chat.page_handle == 'retained'
    assert chat._unresolved_recovery_reason == 'conversation-load-retry-deadline'


@pytest.mark.asyncio
async def test_real_chrome_error_document_reopens_verified_failed_destination():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, channel="chromium")
        try:
            page = await browser.new_page()
            await page.route('**/*', lambda route: route.abort('internetdisconnected'))
            with pytest.raises(Exception, match='ERR_INTERNET_DISCONNECTED'):
                await page.goto(URL)
            await page.wait_for_load_state('domcontentloaded')
            await page.wait_for_selector('#main-frame-error .error-code', timeout=5000)
            failed = await page.evaluate(_SNAPSHOT_FN, [])
            assert failed['domSignals']['browser-network-error']
            assert failed['url'].startswith('chrome-error://')
            await page.unroute('**/*')
            await page.route('**/*', lambda route: route.fulfill(body='<textarea>ready</textarea>', content_type='text/html'))
            # Exercise the production controller: its fresh target lookup
            # supplies the failed destination, not a caller-provided JS arg.
            controller = object.__new__(GptAutoCdpBrowserController)
            current = CdpPageRef('retained', 'target', url=URL)
            controller.page_by_handle = AsyncMock(return_value=current)

            async def evaluate(ref, function, argument):
                assert ref is current
                return await page.evaluate(function, argument)

            controller.evaluate = evaluate
            assert await controller.retry_conversation_load(current, expected_path='/g/g-p-test/c/conversation')
            controller.page_by_handle.assert_awaited_once_with('retained')
            await page.wait_for_selector('textarea')
            assert page.url == URL
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_controller_rejects_recycled_target_before_dom_mutation():
    controller = object.__new__(GptAutoCdpBrowserController)
    controller.page_by_handle = AsyncMock(return_value=CdpPageRef('retained', 'recycled', url=URL))
    controller.evaluate = AsyncMock()
    assert not await controller.retry_conversation_load(
        CdpPageRef('retained', 'original', url=URL), expected_path='/g/g-p-test/c/conversation',
    )
    controller.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_controller_rechecks_actual_route_after_target_lookup():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.route('**/*', lambda route: route.fulfill(body=ERROR, content_type='text/html'))
            # The target ref was resolved before another actor navigated this
            # same target elsewhere. The mutation evaluation must reject it.
            await page.goto('https://chatgpt.com/g/g-p-test/c/other')
            controller = object.__new__(GptAutoCdpBrowserController)
            current = CdpPageRef('retained', 'target', url=URL)
            controller.page_by_handle = AsyncMock(return_value=current)

            async def evaluate(ref, function, argument):
                return await page.evaluate(function, argument)

            controller.evaluate = evaluate
            assert not await controller.retry_conversation_load(current, expected_path='/g/g-p-test/c/conversation')
            assert page.url.endswith('/c/other')
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('url,html', [
    (URL, '<article>' + ERROR + '</article><textarea>quoted error</textarea>'),
    ('https://example.org/g/g-p-test/c/conversation', ERROR),
    ('https://chatgpt.com/g/g-p-test/c/other', ERROR),
])
async def test_network_reload_rejects_quoted_error_or_wrong_conversation(url, html):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html'))
            await page.goto(url)
            assert not await page.evaluate(_RETRY_CONVERSATION_LOAD_FN, {'expectedPath': '/g/g-p-test/c/conversation'})
        finally:
            await browser.close()
