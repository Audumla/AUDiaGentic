"""Regression coverage for ChatGPT's labelled fallback message renderer."""

import pytest
from playwright.async_api import async_playwright

from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import _SNAPSHOT_FN


@pytest.mark.asyncio
async def test_fallback_sibling_action_bar_is_bound_to_latest_response():
    signals = [
        dict(name='completion-control', scope='latest-assistant-turn', selectors=['button[aria-label="Copy"]'], visible=True),
        dict(name='more-actions-menu', scope='latest-assistant-turn', selectors=['button[aria-label="More actions"]'], visible=True),
    ]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content('''<div id="turn"><div>
              <div class="block-BQZwFn"><h4 class="sr-only">You said:</h4><div data-user-message-bubble="true">prompt</div></div>
              <div class="block-BQZwFn"><h4 class="sr-only">ChatGPT said:</h4><p>answer</p></div>
              </div><div class="turn-action-controls"><button aria-label="Copy">Copy</button>
              <button aria-label="More actions">More</button></div></div>''')
            complete = await page.evaluate(_SNAPSHOT_FN, signals)
            assert complete['terminalWitnessAssistantId'] == complete['latestAssistantId']
            assert complete['domSignals']['more-actions-menu']
            await page.evaluate('''document.body.insertAdjacentHTML('beforeend',
              '<div class="block-BQZwFn"><h4 class="sr-only">You said:</h4><div data-user-message-bubble="true">next</div></div><div class="block-BQZwFn">Thinking</div>')''')
            waiting = await page.evaluate(_SNAPSHOT_FN, signals)
            assert waiting['terminalWitnessAssistantId'] is None
            assert not waiting['domSignals']['more-actions-menu']
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_activity_observer_captures_interior_changes_but_not_shimmer():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<div data-message-author-role="user" data-message-id="u1">prompt</div>'
                '<div class="agent-turn">'
                + ''.join(f'<div id="n{i}">AAA</div>' for i in range(600))
                + '</div>'
            )
            before = await page.evaluate(_SNAPSHOT_FN, [])
            await page.evaluate("document.querySelector('#n300').textContent = 'BBB'")
            after = await page.evaluate(_SNAPSHOT_FN, [])
            assert after['domActivityOwnerPromptMessageId'] == 'u1'
            assert after['domActivityDigest'] != before['domActivityDigest']
            await page.evaluate("document.querySelector('#n300').className = 'shimmer-active'")
            animation = await page.evaluate(_SNAPSHOT_FN, [])
            assert animation['domActivityDigest'] == after['domActivityDigest']
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_activity_revision_tracks_reverted_changes_and_rebinds_only_current_root():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content('<div data-message-author-role="user" data-message-id="u1">one</div>'
                '<div id="old" class="agent-turn"><span id="text">AAA</span></div>')
            before = await page.evaluate(_SNAPSHOT_FN, [])
            await page.evaluate("const n=document.querySelector('#text').firstChild; n.nodeValue='BBB'; n.nodeValue='AAA'")
            reverted = await page.evaluate(_SNAPSHOT_FN, [])
            assert reverted['domActivityDigest'] != before['domActivityDigest']
            await page.evaluate("document.querySelector('#old').insertAdjacentHTML('beforeend','<span hidden id=hidden>noise</span>')")
            hidden = await page.evaluate(_SNAPSHOT_FN, [])
            assert hidden['domActivityDigest'] == reverted['domActivityDigest']
            await page.evaluate("document.querySelector('#hidden').remove()")
            assert (await page.evaluate(_SNAPSHOT_FN, []))['domActivityDigest'] == hidden['domActivityDigest']
            await page.evaluate('''document.body.insertAdjacentHTML('beforeend',
              '<div data-message-author-role="user" data-message-id="u2">two</div><div id="current" class="agent-turn">working</div>')''')
            current = await page.evaluate(_SNAPSHOT_FN, [])
            assert current['domActivityOwnerPromptMessageId'] == 'u2'
            await page.evaluate("document.querySelector('#old').textContent='old changed'")
            old_changed = await page.evaluate(_SNAPSHOT_FN, [])
            assert old_changed['domActivityDigest'] == current['domActivityDigest']
            await page.evaluate("document.querySelector('#current').setAttribute('aria-busy','true')")
            assert (await page.evaluate(_SNAPSHOT_FN, []))['domActivityDigest'] != current['domActivityDigest']
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_snapshot_preserves_paragraphs_and_ignores_collapsed_marker() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-user-message-bubble="true">
                    <div class="MarkdownRoot-rZKhxa">
                      <p>first paragraph</p>
                      <p>second paragraph</p>
                      <span aria-hidden="true" class="block">…</span>
                      <button>Show more</button>
                    </div>
                  </div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>finished answer</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["userCount"] == 1
            assert snapshot["assistantCount"] == 1
            assert snapshot["latestUserId"] == "fallback-user-0"
            assert snapshot["latestAssistantId"] == "fallback-assistant-0"
            assert snapshot["messageRefs"][0]["correlationText"] == (
                "first paragraph\nsecond paragraph"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_live_thinking_block_owns_activity_after_latest_prompt() -> None:
    """A pre-assistant fallback block must not reuse the previous turn."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-user-message-bubble="true">old prompt</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>old answer</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-user-message-bubble="true">new prompt</div>
                </div>
                <div class="block-BQZwFn">
                  <div role="status" style="display:block;width:40px;height:20px">Thinking</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["latestUserId"] == "fallback-user-1"
            assert snapshot["domActivityOwnerPromptMessageId"] == "fallback-user-1"
            assert snapshot["latestAssistantText"] == "old answer"
            assert snapshot["terminalWitnessAssistantId"] is None
            assert snapshot["progressBlocks"][0]["ownerPromptMessageId"] == "fallback-user-1"
            assert snapshot["progressBlocks"][0]["kind"] == "dom-status"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_real_message_id_read_from_descendant_carrier() -> None:
    """The real ChatGPT UUID lives on a descendant, not the block or the
    dead `[data-user-message-bubble="true"]` selector; it must be used."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div class="group/user-message" data-chatgpt-search-message-ids="real-user-uuid">prompt</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div data-chatgpt-search-message-ids="real-assistant-uuid">answer</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["latestUserId"] == "real-user-uuid"
            assert snapshot["latestAssistantId"] == "real-assistant-uuid"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_ordinal_stays_stable_across_mixed_real_and_synthetic_ids() -> None:
    """The synthetic ordinal must advance for every block of a role, even
    when some blocks resolve a real id -- otherwise a later missing-id
    block can collide with an earlier synthetic id (id reuse across
    distinct messages, not merely a fail-closed miss)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div>first prompt, no real id</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>first answer, no real id</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-chatgpt-search-message-ids="real-user-uuid">second prompt, real id</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>second answer, no real id</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            user_ids = [m["messageId"] for m in snapshot["messageRefs"] if m["role"] == "user"]
            assistant_ids = [m["messageId"] for m in snapshot["messageRefs"] if m["role"] == "assistant"]
            assert user_ids == ["fallback-user-0", "real-user-uuid"]
            assert assistant_ids == ["fallback-assistant-0", "fallback-assistant-1"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_multi_id_carrier_is_ambiguous_and_falls_back_to_synthetic() -> None:
    """A carrier with more than one space-separated id has no proven
    canonical token; scalarizing to the first would let the apparent id
    change across polls, so it must fail closed to the synthetic id."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-chatgpt-search-message-ids="id-a id-b">prompt</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>answer</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["latestUserId"] == "fallback-user-0"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_nested_block_carrier_is_foreign_and_falls_back_to_synthetic() -> None:
    """A `data-chatgpt-search-message-ids` carrier whose nearest
    `.block-BQZwFn` ancestor is a different (nested) block belongs to that
    other semantic message, not this one, and must not be adopted."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div>outer prompt wrapper
                    <div class="block-BQZwFn" data-chatgpt-search-message-ids="nested-foreign-id">
                      nested unrelated block
                    </div>
                  </div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>answer</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["latestUserId"] == "fallback-user-0"
        finally:
            await browser.close()
