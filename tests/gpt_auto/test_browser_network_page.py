from __future__ import annotations

import pytest
from playwright.async_api import async_playwright
from types import SimpleNamespace
from unittest.mock import AsyncMock

from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat

from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
    _RETRY_CONVERSATION_LOAD_FN, _SNAPSHOT_FN,
)

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
async def test_persistent_network_error_does_not_create_replacement_tabs():
    chat = object.__new__(PersistentChat)
    chat.page_handle = 'retained'
    chat.chat_url = URL
    chat.active_turn_id = None
    chat.unresolved_turn_pending = False
    chat.config = SimpleNamespace(
        chat=SimpleNamespace(ready_timeout_seconds=0.02),
        turn=SimpleNamespace(poll_interval_seconds=0.01),
        workflow=SimpleNamespace(recovery=SimpleNamespace(
            conversation_load_failure_recovery_enabled=True, action_pause_seconds=0)),
    )
    chat.retry_conversation_load = AsyncMock(return_value=True)
    chat._prefer_active_conversation_page = AsyncMock()
    chat._create_recovery_page = AsyncMock()
    error = SimpleNamespace(dom_signals=frozenset({'browser-network-error', 'conversation-load-failed'}))
    assert not await chat._replace_load_failed_page(error)
    chat.retry_conversation_load.assert_awaited_once()
    chat._prefer_active_conversation_page.assert_not_awaited()
    chat._create_recovery_page.assert_not_awaited()
    assert chat.page_handle == 'retained'
    assert chat._unresolved_recovery_reason == 'browser-network-recovery-deadline'


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
            assert await page.evaluate(_RETRY_CONVERSATION_LOAD_FN, {
                'expectedPath': '/g/g-p-test/c/conversation', 'browserTargetUrl': URL,
            })
            await page.wait_for_selector('textarea')
            assert page.url == URL
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
