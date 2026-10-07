"""Regression coverage for ChatGPT's labelled fallback message renderer."""

import pytest
from playwright.async_api import async_playwright

from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
    _RETRY_CONVERSATION_LOAD_FN,
    _RETRY_DELIVERY_TIMEOUT_FN,
    _SNAPSHOT_FN,
)

# The exact markup captured live 2026-09-27 from a stuck ChatGPT conversation:
# a role="alert" aside with a plain <button>Retry</button> that carries
# neither aria-label nor data-testid.
_LIVE_STREAM_RECOVERY_TIMEOUT_ALERT_HTML = """
<aside role="alert" class="text-danger">
  <div>ChatGPT stream recovery polling timed out</div>
  <button type="button" class="rounded-full border-default">Retry</button>
</aside>
"""

_DELIVERY_TIMEOUT_RETRY_SIGNAL = dict(
    name="delivery-timeout-retry",
    scope="document",
    selectors=[
        'button[data-testid="regenerate-thread-error-button"]',
        'button[aria-label="Retry"]',
        'button[data-testid*="regenerate"][data-testid*="error"]',
    ],
    visible=True,
    textContainsAny=["retry"],
)

# The current renderer's plain-text Retry control has neither aria-label nor
# data-testid, so it is identified by its alert's own known message text
# instead of by button attributes -- see gpt-auto-defaults.yaml. Matching by
# an exact known phrase (rather than the generic `[role="alert"] button` +
# substring "retry" first attempted) avoids firing on an unrelated alert
# whose own Retry-ish button would otherwise permanently consume the
# turn's one-shot retry attempt before the real control is ever found.
_DELIVERY_TIMEOUT_ALERT_SIGNAL = dict(
    name="delivery-timeout-alert",
    scope="document",
    selectors=['[role="alert"]'],
    visible=True,
    textContainsAny=["stream recovery polling timed out"],
)

_CONVERSATION_LOAD_FAILED_SIGNAL = dict(
    name="conversation-load-failed",
    scope="document",
    selectors=["body"],
    visible=True,
    textContainsAny=[
        "Could not load this ChatGPT conversation",
        "Could not load this ChatGPT conversation.",
    ],
)

_STREAM_CACHE_EXPIRED_SIGNAL = dict(
    name="stream-cache-expired",
    scope="document",
    selectors=["body"],
    visible=True,
    textContainsAny=["Stream cache expired"],
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Could not load this ChatGPT conversation",
        "Could not load this ChatGPT conversation.",
    ],
)
async def test_conversation_load_failure_matches_current_and_legacy_renderer_text(message):
    """The live error page currently drops the trailing period."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(f"<body>{message}<button>Retry</button></body>")
            snapshot = await page.evaluate(_SNAPSHOT_FN, [_CONVERSATION_LOAD_FAILED_SIGNAL])
            assert snapshot["domSignals"]["conversation-load-failed"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_document_stream_cache_error_ignores_text_inside_conversation_messages():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<div class="block-BQZwFn"><h4 class="sr-only">You said:</h4>'
                '<div class="group/user-message">Stream cache expired</div></div>'
            )
            quoted = await page.evaluate(_SNAPSHOT_FN, [_STREAM_CACHE_EXPIRED_SIGNAL])
            assert not quoted["domSignals"]["stream-cache-expired"]

            await page.set_content('<div class="provider-error">Stream cache expired</div>')
            provider_error = await page.evaluate(_SNAPSHOT_FN, [_STREAM_CACHE_EXPIRED_SIGNAL])
            assert provider_error["domSignals"]["stream-cache-expired"]
        finally:
            await browser.close()


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
async def test_fallback_outer_turn_action_bar_is_bound_to_latest_response():
    """The live renderer may put the assistant bar above the message block.

    The user prompt has its own Copy message bar, so completion controls must
    be selected from the assistant's ancestor turn wrapper rather than with a
    document-wide selector.
    """
    signals = [
        dict(name='completion-control', scope='latest-assistant-turn', selectors=['button[aria-label="Copy"]', 'button[aria-label="Copy message"]'], visible=True),
        dict(name='more-actions-menu', scope='latest-assistant-turn', selectors=['button[aria-label="More actions"]'], visible=True),
    ]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content('''
              <div class="turn-shell">
                <div class="message-list">
                  <div class="block-BQZwFn"><h4 class="sr-only">You said:</h4>
                    <div class="group/user-message">prompt</div>
                    <div class="turn-action-controls"><button aria-label="Copy message">Copy</button></div>
                  </div>
                  <div class="block-BQZwFn"><h4 class="sr-only">ChatGPT said:</h4>
                    <div>answer</div>
                  </div>
                </div>
                <div class="group flex flex-col">
                  <div class="turn-action-controls"><button aria-label="Copy">Copy</button>
                    <button aria-label="More actions">More</button></div>
                </div>
              </div>''')
            complete = await page.evaluate(_SNAPSHOT_FN, signals)
            assert complete['domSignals']['completion-control']
            assert complete['domSignals']['more-actions-menu']
            assert complete['terminalWitnessAssistantId'] == complete['latestAssistantId']
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_current_renderer_turn_root_includes_sibling_completion_bar():
    """The current renderer puts controls outside the labelled block."""
    signals = [
        dict(name='completion-control', scope='latest-assistant-turn', selectors=['button[aria-label="Copy message"]'], visible=True),
        dict(name='more-actions-menu', scope='latest-assistant-turn', selectors=['button[aria-label="More actions"]'], visible=True),
    ]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content('''
              <div data-turn-key="prompt-id">
                <div data-content-search-turn-key="fallback-turn-0">
                  <div class="block-BQZwFn"><h4 class="sr-only">You said:</h4>
                    <div data-user-message-bubble="true">prompt</div>
                    <button aria-label="Copy message">Copy</button>
                  </div>
                  <div class="block-BQZwFn"><h4 class="sr-only">ChatGPT said:</h4>
                    <p>answer</p>
                  </div>
                </div>
                <div class="assistant-actions">
                  <button aria-label="Copy message">Copy</button>
                  <button aria-label="More actions">More</button>
                </div>
              </div>''')
            snapshot = await page.evaluate(_SNAPSHOT_FN, signals)
            assert snapshot['domSignals']['completion-control']
            assert snapshot['domSignals']['more-actions-menu']
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
            await page.evaluate("document.querySelector('#n300').className = 'progress-active'")
            meaningful_class = await page.evaluate(_SNAPSHOT_FN, [])
            assert meaningful_class['domActivityDigest'] != animation['domActivityDigest']
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
async def test_unlabelled_fallback_activity_block_still_renews_dom_activity():
    """Visible work can precede both role nodes and fallback labels."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<div class="block-BQZwFn">'
                '<div role="status" style="display:block;width:40px;height:20px">'
                'Inspecting commit metadata</div></div>'
            )
            before = await page.evaluate(_SNAPSHOT_FN, [])
            assert before["userCount"] == 0
            assert before["assistantCount"] == 0
            assert before["domActivityDigest"]
            assert before["domActivityOwnerPromptMessageId"] is None

            await page.locator('[role="status"]').evaluate(
                "node => node.textContent = 'Reviewed lifecycle paths'"
            )
            after = await page.evaluate(_SNAPSHOT_FN, [])
            assert after["domActivityDigest"] != before["domActivityDigest"]
            assert after["domActivityOwnerPromptMessageId"] is None
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
async def test_fallback_pre_prompt_activity_block_owns_live_activity_with_stop_control() -> None:
    """The live renderer may place its unlabelled activity block before the prompt."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <div class="summary-lK7Lpm" style="display:block;width:40px;height:20px">
                    Inspected GPT Auto adapter files, diffs, and configuration logic
                  </div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-user-message-bubble="true">current prompt</div>
                </div>
                <button aria-label="Stop" style="display:block;width:40px;height:20px">Stop</button>
                """
            )

            before = await page.evaluate(_SNAPSHOT_FN, [])
            assert before["latestUserId"] == "fallback-user-0"
            # Stop proves only conversation-level liveness.  The first
            # pre-prompt observation cannot prove that this block belongs to
            # the current prompt.
            assert before["domActivityOwnerPromptMessageId"] is None
            assert not before["progressBlocks"]

            await page.locator(".summary-lK7Lpm").evaluate(
                "node => node.textContent = 'Evaluated recovery evidence'"
            )
            after = await page.evaluate(_SNAPSHOT_FN, [])
            assert after["domActivityDigest"] != before["domActivityDigest"]
            assert after["domActivityOwnerPromptMessageId"] == "fallback-user-0"
            assert after["progressBlocks"]
            assert after["progressBlocks"][0]["ownerPromptMessageId"] == "fallback-user-0"
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
    distinct messages, not merely a fail-closed miss).

    A no-id -> real-id -> no-id sequence per role is required to actually
    pin this: the prior buggy `realMessageId(block) || fallback-${i++}`
    implementation only advanced the ordinal on the synthetic branch, so it
    would produce fallback-user-1 (not -2) for the third user block here --
    a two-block no-id/real-id sequence cannot distinguish the two
    implementations because there is no third block for the stale ordinal
    to collide into."""
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
                  <div data-chatgpt-search-message-ids="real-assistant-uuid">second answer, real id</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div>third prompt, no real id</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>third answer, no real id</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            user_ids = [m["messageId"] for m in snapshot["messageRefs"] if m["role"] == "user"]
            assistant_ids = [m["messageId"] for m in snapshot["messageRefs"] if m["role"] == "assistant"]
            assert user_ids == ["fallback-user-0", "real-user-uuid", "fallback-user-2"]
            assert assistant_ids == ["fallback-assistant-0", "real-assistant-uuid", "fallback-assistant-2"]
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
async def test_delivery_timeout_alert_signal_detects_known_alert_text() -> None:
    """The current renderer's Retry control has no aria-label or
    data-testid, so it cannot be found by delivery-timeout-retry's
    button-attribute selectors; delivery-timeout-alert must detect the
    known alert message text instead."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_LIVE_STREAM_RECOVERY_TIMEOUT_ALERT_HTML)

            snapshot = await page.evaluate(
                _SNAPSHOT_FN, [_DELIVERY_TIMEOUT_RETRY_SIGNAL, _DELIVERY_TIMEOUT_ALERT_SIGNAL]
            )

            assert snapshot["domSignals"]["delivery-timeout-retry"] is False
            assert snapshot["domSignals"]["delivery-timeout-alert"] is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_delivery_timeout_alert_signal_ignores_unrelated_alert_with_retry_button() -> None:
    """An unrelated role="alert" that happens to contain a differently
    meant Retry-labelled button (e.g. "Retry upload") must NOT satisfy
    delivery-timeout-alert: it does not carry the known stream-recovery
    message text, so it must not consume the turn's one-shot retry
    attempt before the real control is ever found. This is the exact
    signal/click divergence an earlier, broader `[role="alert"] button` +
    substring "retry" attempt introduced."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<aside role="alert"><div>Upload failed</div>'
                '<button type="button">Retry upload</button></aside>'
            )

            snapshot = await page.evaluate(
                _SNAPSHOT_FN, [_DELIVERY_TIMEOUT_RETRY_SIGNAL, _DELIVERY_TIMEOUT_ALERT_SIGNAL]
            )

            assert snapshot["domSignals"]["delivery-timeout-retry"] is False
            assert snapshot["domSignals"]["delivery-timeout-alert"] is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_retry_conversation_load_clicks_only_exact_provider_retry() -> None:
    """Conversation-load recovery clicks the same-chat Retry control only."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<main>Could not load this ChatGPT conversation</main>'
                '<button type="button">Retry</button>'
                '<button type="button">Retry upload</button>'
            )
            await page.evaluate(
                """for (const button of document.querySelectorAll('button')) {
                    button.addEventListener('click', () => { button.dataset.clicked = 'true'; });
                }"""
            )

            clicked = await page.evaluate(_RETRY_CONVERSATION_LOAD_FN)

            assert clicked is True
            assert await page.evaluate("document.querySelectorAll('button')[0].dataset.clicked") == "true"
            assert await page.evaluate("document.querySelectorAll('button')[1].dataset.clicked") is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_retry_conversation_load_ignores_retry_without_load_error() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content('<main>Ready</main><button type="button">Retry</button>')
            clicked = await page.evaluate(_RETRY_CONVERSATION_LOAD_FN)
            assert clicked is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_retry_delivery_timeout_clicks_plain_text_alert_button() -> None:
    """The actual click function (module-level _RETRY_DELIVERY_TIMEOUT_FN,
    the same code retry_delivery_timeout() evaluates) must find and click
    the live-captured plain-text Retry control."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_LIVE_STREAM_RECOVERY_TIMEOUT_ALERT_HTML)
            await page.evaluate(
                "document.querySelector('button').addEventListener("
                "'click', () => { document.querySelector('button').dataset.clicked = 'true'; })"
            )

            clicked = await page.evaluate(_RETRY_DELIVERY_TIMEOUT_FN)

            assert clicked is True
            assert await page.evaluate("document.querySelector('button').dataset.clicked") == "true"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_retry_delivery_timeout_clicks_resume_stream_unavailable_button() -> None:
    """The current provider wording uses the same request-owned Retry path."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<aside role="alert"><div>Resume stream unavailable</div>'
                '<button type="button">Retry</button></aside>'
            )
            await page.evaluate(
                "document.querySelector('button').addEventListener("
                "'click', () => { document.querySelector('button').dataset.clicked = 'true'; })"
            )

            clicked = await page.evaluate(_RETRY_DELIVERY_TIMEOUT_FN)

            assert clicked is True
            assert await page.evaluate("document.querySelector('button').dataset.clicked") == "true"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_retry_delivery_timeout_never_clicks_a_non_retry_button() -> None:
    """A visible, enabled button in an unrelated role="alert" whose text is
    not exactly "retry" must never be activated."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<aside role="alert"><div>Something went wrong</div>'
                '<button type="button">Dismiss</button></aside>'
            )
            await page.evaluate(
                "document.querySelector('button').addEventListener("
                "'click', () => { document.querySelector('button').dataset.clicked = 'true'; })"
            )

            clicked = await page.evaluate(_RETRY_DELIVERY_TIMEOUT_FN)

            assert clicked is False
            assert await page.evaluate("document.querySelector('button').dataset.clicked") is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_retry_delivery_timeout_never_clicks_an_unrelated_alerts_retry_button() -> None:
    """An unrelated alert's own Retry-labelled button (e.g. an upload
    failure's "Retry upload", whose accessible text after normalization is
    not exactly "retry") must never be clicked, and critically: an alert
    that does not carry the known stream-recovery-timeout message text
    must never be scanned for a retry button at all, even if one of its
    buttons happens to have exactly the text "Retry". This is the
    signal/click divergence fix: only the specific known alert is ever a
    candidate scope."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                '<aside role="alert"><div>Upload failed</div>'
                '<button type="button">Retry</button></aside>'
            )
            await page.evaluate(
                "document.querySelector('button').addEventListener("
                "'click', () => { document.querySelector('button').dataset.clicked = 'true'; })"
            )

            clicked = await page.evaluate(_RETRY_DELIVERY_TIMEOUT_FN)

            assert clicked is False
            assert await page.evaluate("document.querySelector('button').dataset.clicked") is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_foreign_carrier_does_not_shadow_a_later_owned_carrier() -> None:
    """A first-encountered foreign/nested carrier must not stop the search:
    a later descendant carrier that IS owned by this block must still be
    found and used, not discarded because querySelector found the foreign
    one first."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div class="block-BQZwFn" data-chatgpt-search-message-ids="foreign">nested unrelated block</div>
                  <div data-chatgpt-search-message-ids="real-user-uuid">prompt</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>answer</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["latestUserId"] == "real-user-uuid"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_two_owned_carriers_with_different_ids_is_ambiguous() -> None:
    """Two carriers both owned by the same block but disagreeing on the id
    must fail closed to the synthetic id, not silently adopt whichever one
    DOM order or querySelector happens to return first."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-chatgpt-search-message-ids="id-a">part one</div>
                  <div data-chatgpt-search-message-ids="id-b">part two</div>
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
async def test_fallback_two_owned_carriers_agreeing_on_id_resolve_to_it() -> None:
    """Two carriers owned by the same block that agree on the same id are
    not ambiguous -- the shared id must be used, not discarded."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-chatgpt-search-message-ids="shared-id">part one</div>
                  <div data-chatgpt-search-message-ids="shared-id">part two</div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>answer</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["latestUserId"] == "shared-id"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_current_renderer_units_restore_prompt_and_repeated_assistant_identity() -> None:
    """The current ChatGPT fallback renderer has no legacy role headings.

    Its user UUID is carried by the user block's ancestor, while the
    assistant UUID is repeated in one search-message attribute.  Both must
    remain request-correlatable for completion detection and operator capture.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <div class="group/user-message" data-chatgpt-search-message-ids="real-user-uuid">
                    <div data-content-search-unit-key="fallback-turn-0:0:user">prompt</div>
                  </div>
                </div>
                <div class="block-BQZwFn">
                  <div data-content-search-unit-key="fallback-turn-0:2:assistant"
                       data-chatgpt-search-message-ids="real-assistant-uuid real-assistant-uuid">
                    <h4 class="sr-only">ChatGPT said:</h4>
                    <div>answer</div>
                  </div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["userCount"] == 1
            assert snapshot["assistantCount"] == 1
            assert snapshot["latestUserId"] == "real-user-uuid"
            assert snapshot["latestAssistantId"] == "real-assistant-uuid"
            assert snapshot["latestUserText"] == "prompt"
            assert snapshot["latestAssistantText"] == "answer"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_unlabelled_wrapper_does_not_adopt_a_nested_blocks_label() -> None:
    """An unlabelled outer `.block-BQZwFn` wrapping a labelled nested block
    must not adopt the nested block's h4 label -- that would turn one
    semantic message into two messageEntries (the outer wrapper plus the
    inner block), inflating userCount and shifting every later ordinal."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  wrapper, no label of its own
                  <div class="block-BQZwFn" data-chatgpt-search-message-ids="u1">
                    <h4 class="sr-only">You said:</h4>
                    <div>prompt</div>
                  </div>
                </div>
                <div class="block-BQZwFn">
                  <h4 class="sr-only">ChatGPT said:</h4>
                  <div>answer</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["userCount"] == 1
            assert snapshot["latestUserId"] == "u1"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_real_user_id_propagates_to_activity_ownership() -> None:
    """A real user id must propagate through to domActivityOwnerPromptMessageId
    and progressBlocks ownership exactly like a synthetic id does -- the
    scoping in _scope_response_snapshot()/turn.py compares raw message ids,
    so a real id must not be treated differently from a fallback-user-N id
    by that comparison."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """
                <div class="block-BQZwFn">
                  <h4 class="sr-only">You said:</h4>
                  <div data-chatgpt-search-message-ids="real-u">prompt</div>
                </div>
                <div class="block-BQZwFn">
                  <div role="status" style="display:block;width:40px;height:20px">Thinking</div>
                </div>
                """
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, [])

            assert snapshot["latestUserId"] == "real-u"
            assert snapshot["domActivityOwnerPromptMessageId"] == "real-u"
            assert snapshot["progressBlocks"][0]["ownerPromptMessageId"] == "real-u"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_real_assistant_id_binds_terminal_witness() -> None:
    """A real assistant id must satisfy the same sibling-action-bar terminal
    witness binding a synthetic fallback-assistant-N id does."""
    signals = [
        dict(name='completion-control', scope='latest-assistant-turn', selectors=['button[aria-label="Copy"]'], visible=True),
        dict(name='more-actions-menu', scope='latest-assistant-turn', selectors=['button[aria-label="More actions"]'], visible=True),
    ]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """<div id="turn"><div>
                  <div class="block-BQZwFn"><h4 class="sr-only">You said:</h4>
                    <div data-chatgpt-search-message-ids="real-u">prompt</div></div>
                  <div class="block-BQZwFn"><h4 class="sr-only">ChatGPT said:</h4>
                    <div data-chatgpt-search-message-ids="real-a"><p>answer</p></div></div>
                  </div><div class="turn-action-controls"><button aria-label="Copy">Copy</button>
                  <button aria-label="More actions">More</button></div></div>"""
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, signals)

            assert snapshot["latestAssistantId"] == "real-a"
            assert snapshot["terminalWitnessAssistantId"] == "real-a"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_reverse_dom_order_uses_visual_conversation_order() -> None:
    """A newest-first DOM must not make a completed response look unanswered."""
    signals = [
        dict(name='completion-control', scope='latest-assistant-turn', selectors=['button[aria-label="Copy"]'], visible=True),
        dict(name='more-actions-menu', scope='latest-assistant-turn', selectors=['button[aria-label="More actions"]'], visible=True),
    ]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """<div id="turn"><div style="display:flex;flex-direction:column-reverse">
                  <div class="block-BQZwFn"><h4 class="sr-only">ChatGPT said:</h4>
                    <div data-chatgpt-search-message-ids="real-a"><p>answer</p></div></div>
                  <div class="block-BQZwFn"><h4 class="sr-only">You said:</h4>
                    <div data-user-message-bubble="true"
                         data-chatgpt-search-message-ids="real-u">prompt</div></div>
                  </div><div class="turn-action-controls"><button aria-label="Copy">Copy</button>
                  <button aria-label="More actions">More</button></div></div>"""
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, signals)

            assert [ref["role"] for ref in snapshot["messageRefs"]] == ["user", "assistant"]
            assert snapshot["latestUserId"] == "real-u"
            assert snapshot["latestAssistantId"] == "real-a"
            assert snapshot["terminalWitnessAssistantId"] == "real-a"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fallback_shared_turn_key_beats_zero_geometry_dom_order() -> None:
    """A provider-paired completed turn is authoritative without layout."""
    signals = [
        dict(name='completion-control', scope='latest-assistant-turn', selectors=['button[aria-label="Copy"]'], visible=True),
        dict(name='more-actions-menu', scope='latest-assistant-turn', selectors=['button[aria-label="More actions"]'], visible=True),
    ]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                """<div id="turn"><div>
                  <div class="block-BQZwFn" data-content-search-turn-key="provider-turn-1">
                    <h4 class="sr-only">ChatGPT said:</h4>
                    <div data-chatgpt-search-message-ids="real-a"><p>answer</p></div></div>
                  <div class="block-BQZwFn" data-content-search-turn-key="provider-turn-1">
                    <h4 class="sr-only">You said:</h4>
                    <div data-user-message-bubble="true"
                         data-chatgpt-search-message-ids="real-u">prompt</div></div>
                  </div><div class="turn-action-controls"><button aria-label="Copy">Copy</button>
                  <button aria-label="More actions">More</button></div></div>"""
            )
            await page.evaluate(
                """document.querySelectorAll('.block-BQZwFn').forEach(
                  block => block.getBoundingClientRect = () => ({
                    top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0
                  })
                )"""
            )

            snapshot = await page.evaluate(_SNAPSHOT_FN, signals)

            assert [ref["role"] for ref in snapshot["messageRefs"]] == ["user", "assistant"]
            assert snapshot["latestUserId"] == "real-u"
            assert snapshot["latestAssistantId"] == "real-a"
            assert snapshot["terminalWitnessAssistantId"] == "real-a"
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
