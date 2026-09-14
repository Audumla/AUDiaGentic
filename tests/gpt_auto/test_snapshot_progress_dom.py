"""Real-DOM coverage for request-owned structural GPT activity signals."""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from audiagentic.components.providers.adapters.gpt_auto.cdp.cdp_browser import CdpPageRef
from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
    GptAutoCdpBrowserController,
)


async def _snapshot(page, monkeypatch: pytest.MonkeyPatch) -> dict:
    controller = GptAutoCdpBrowserController(object())

    async def evaluate(_ref, function, argument=None):
        return await page.evaluate(function, argument)

    monkeypatch.setattr(controller, "evaluate", evaluate)
    return await controller.snapshot(CdpPageRef("test", "test"))


_BASE = """
<style>.box { display:block; width:40px; height:20px; }</style>
<div data-message-author-role="user" data-message-id="prompt-1">Prompt</div>
"""


@pytest.mark.asyncio
async def test_unknown_status_is_request_owned_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + """
                <div class="agent-turn">
                  <div class="box" role="status" data-phase="working">処理しています</div>
                </div>
            """)
            snapshot = await _snapshot(page, monkeypatch)
            blocks = snapshot["progressBlocks"]
            assert len(blocks) == 1
            assert blocks[0]["ownerPromptMessageId"] == "prompt-1"
            assert blocks[0]["kind"] == "dom-status"
            assert len(blocks[0]["digest"]) == 16
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_semantic_and_non_text_changes_update_structural_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + """
                <div class="agent-turn">
                  <div id="progress" class="box" data-testid="progress-meter"
                       aria-valuenow="10" aria-valuetext="10 percent"
                       data-phase="fetch" data-progress="10"></div>
                  <table id="result"><tbody><tr><td>A</td></tr></tbody></table>
                </div>
            """)
            before = await _snapshot(page, monkeypatch)
            before_by_kind = {item["kind"]: item["digest"] for item in before["progressBlocks"]}

            await page.evaluate("""
                () => {
                  const progress = document.querySelector("#progress");
                  progress.setAttribute("aria-valuenow", "20");
                  progress.setAttribute("data-phase", "parse");
                  progress.setAttribute("data-progress", "20");
                  document.querySelector("#result tbody").insertRow().insertCell().textContent = "B";
                }
            """)
            after = await _snapshot(page, monkeypatch)
            after_by_kind = {item["kind"]: item["digest"] for item in after["progressBlocks"]}

            assert before_by_kind["dom-progress"] != after_by_kind["dom-progress"]
            assert before_by_kind["dom-table"] != after_by_kind["dom-table"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_hidden_descendant_does_not_change_visible_region_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + """
                <div class="agent-turn">
                  <div id="tool" class="box" data-testid="tool-result">
                    <span id="hidden" style="display:none" data-state="old"></span>
                  </div>
                </div>
            """)
            before = await _snapshot(page, monkeypatch)
            await page.evaluate("document.querySelector('#hidden').setAttribute('data-state', 'new')")
            after = await _snapshot(page, monkeypatch)
            assert before["progressBlocks"][0]["digest"] == after["progressBlocks"][0]["digest"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_late_visible_semantic_state_changes_region_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            children = "".join(
                f'<span class="box" data-phase="phase-{index}"></span>'
                for index in range(80)
            )
            await page.set_content(_BASE + f'<div class="agent-turn"><div id="region" data-testid="tool-result">{children}</div></div>')
            before = await _snapshot(page, monkeypatch)
            await page.evaluate("document.querySelector('#region').lastElementChild.setAttribute('data-phase', 'late-change')")
            after = await _snapshot(page, monkeypatch)
            assert before["progressBlocks"][0]["digest"] != after["progressBlocks"][0]["digest"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_structural_kinds_are_extracted_from_owned_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + """
                <div class="agent-turn">
                  <div class="box group/tool-message"></div>
                  <div class="box" data-testid="connector-card"></div>
                  <div class="box" data-testid="citation-pill"></div>
                  <table><tbody><tr><td>row</td></tr></tbody></table>
                  <div class="box" data-testid="writing-block-container"></div>
                </div>
            """)
            snapshot = await _snapshot(page, monkeypatch)
            kinds = {item["kind"] for item in snapshot["progressBlocks"]}
            assert {
                "dom-tool-result", "dom-connector", "dom-citation",
                "dom-table", "dom-materialization",
            } <= kinds
        finally:
            await browser.close()
