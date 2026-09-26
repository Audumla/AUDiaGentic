"""Regression coverage for ChatGPT's labelled fallback message renderer."""

import pytest
from playwright.async_api import async_playwright

from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import _SNAPSHOT_FN


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
