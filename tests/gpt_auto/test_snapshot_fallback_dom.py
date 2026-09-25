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
