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
                    <span id="hidden" style="display:none" data-state="old">hidden-old</span>
                  </div>
                </div>
            """)
            before = await _snapshot(page, monkeypatch)
            await page.evaluate("document.querySelector('#hidden').setAttribute('data-state', 'new')")
            after = await _snapshot(page, monkeypatch)
            assert before["progressBlocks"][0]["digest"] == after["progressBlocks"][0]["digest"]
            await page.evaluate("document.querySelector('#hidden').textContent = 'hidden-new'")
            after = await _snapshot(page, monkeypatch)
            assert before["progressBlocks"][0]["digest"] == after["progressBlocks"][0]["digest"]
            await page.evaluate("""
                () => {
                  const child = document.createElement('span');
                  child.style.display = 'none';
                  child.dataset.phase = 'hidden-phase';
                  child.textContent = 'hidden-inserted';
                  document.querySelector('#tool').appendChild(child);
                }
            """)
            after = await _snapshot(page, monkeypatch)
            assert before["progressBlocks"][0]["digest"] == after["progressBlocks"][0]["digest"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_opacity_hidden_text_and_insertion_do_not_change_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + """
                <div class="agent-turn">
                  <div id="tool" class="box" data-testid="tool-result">
                    <span id="hidden" style="opacity:0">old</span>
                  </div>
                </div>
            """)
            before = await _snapshot(page, monkeypatch)
            await page.evaluate("document.querySelector('#hidden').textContent = 'new'")
            await page.evaluate("""
                () => {
                  const child = document.createElement('span');
                  child.style.opacity = '0';
                  child.textContent = 'inserted';
                  document.querySelector('#tool').appendChild(child);
                }
            """)
            after = await _snapshot(page, monkeypatch)
            assert before["progressBlocks"][0]["digest"] == after["progressBlocks"][0]["digest"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_large_attributes_do_not_hide_late_semantic_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            huge = "X" * 12000
            await page.set_content(_BASE + f'<div class="agent-turn"><div id="progress" class="box" data-testid="progress-meter" aria-label="{huge}" data-phase="one"></div></div>')
            before = await _snapshot(page, monkeypatch)
            await page.evaluate("document.querySelector('#progress').setAttribute('data-phase', 'two')")
            after = await _snapshot(page, monkeypatch)
            assert before["progressBlocks"][0]["digest"] != after["progressBlocks"][0]["digest"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_lexical_child_is_canonical_activity_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + """
                <div class="agent-turn">
                  <div class="box" data-testid="tool-result">
                    <span class="box">Fetching source</span>
                  </div>
                </div>
            """)
            snapshot = await _snapshot(page, monkeypatch)
            assert [item["kind"] for item in snapshot["progressBlocks"]].count("fetching") == 1
            assert "dom-tool-result" in [item["kind"] for item in snapshot["progressBlocks"]]
            before = {item["kind"]: item["digest"] for item in snapshot["progressBlocks"]}
            await page.evaluate("document.querySelector('span').textContent = 'Fetching next source'")
            child_changed = {item["kind"]: item["digest"] for item in (await _snapshot(page, monkeypatch))["progressBlocks"]}
            assert child_changed["fetching"] != before["fetching"]
            assert child_changed["dom-tool-result"] == before["dom-tool-result"]
            await page.evaluate("document.querySelector('[data-testid=tool-result]').setAttribute('data-state', 'complete')")
            parent_changed = {item["kind"]: item["digest"] for item in (await _snapshot(page, monkeypatch))["progressBlocks"]}
            assert parent_changed["fetching"] == child_changed["fetching"]
            assert parent_changed["dom-tool-result"] != child_changed["dom-tool-result"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_hidden_insert_and_remove_are_structurally_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + """
                <div class="agent-turn">
                  <div id="tool" class="box" data-testid="tool-result"></div>
                </div>
            """)
            base_digest = (await _snapshot(page, monkeypatch))["progressBlocks"][0]["digest"]
            await page.evaluate("""
                () => {
                  const child = document.createElement('span');
                  child.id = 'hidden-transient';
                  child.style.opacity = '0';
                  child.textContent = 'Fetching hidden source';
                  document.querySelector('#tool').appendChild(child);
                }
            """)
            assert (await _snapshot(page, monkeypatch))["progressBlocks"][0]["digest"] == base_digest
            await page.evaluate("document.querySelector('#hidden-transient').remove()")
            assert (await _snapshot(page, monkeypatch))["progressBlocks"][0]["digest"] == base_digest
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_large_visible_text_tail_change_updates_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + '<div class="agent-turn"><div id="tool" data-testid="tool-result"></div></div>')
            await page.evaluate("(value) => document.querySelector('#tool').textContent = value", "A" * 12000 + "TAIL-ONE")
            before = (await _snapshot(page, monkeypatch))["progressBlocks"][0]["digest"]
            await page.evaluate("(value) => document.querySelector('#tool').textContent = value", "A" * 12000 + "TAIL-TWO")
            after = (await _snapshot(page, monkeypatch))["progressBlocks"][0]["digest"]
            assert before != after
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_structural_semantic_wrapper_survives_nested_lexical_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_BASE + '<div class="agent-turn"><div id="tool" class="box" data-testid="tool-result"><div id="state" data-state="working"><span id="lexical" class="box">Fetching source</span></div></div></div>')
            initial = {item["kind"]: item["digest"] for item in (await _snapshot(page, monkeypatch))["progressBlocks"]}
            await page.evaluate("document.querySelector('#lexical').textContent = 'Fetching next source'")
            lexical_changed = {item["kind"]: item["digest"] for item in (await _snapshot(page, monkeypatch))["progressBlocks"]}
            assert lexical_changed["fetching"] != initial["fetching"]
            assert lexical_changed["dom-tool-result"] == initial["dom-tool-result"]
            await page.evaluate("document.querySelector('#state').dataset.state = 'complete'")
            structural_changed = {item["kind"]: item["digest"] for item in (await _snapshot(page, monkeypatch))["progressBlocks"]}
            assert structural_changed["fetching"] == lexical_changed["fetching"]
            assert structural_changed["dom-tool-result"] != lexical_changed["dom-tool-result"]
            await page.evaluate("document.querySelector('#state').remove()")
            assert "dom-tool-result" in [item["kind"] for item in (await _snapshot(page, monkeypatch))["progressBlocks"]]
            await page.evaluate("""
                () => document.querySelector('#tool').insertAdjacentHTML(
                  'beforeend',
                  '<div id="state" data-state="complete"><span id="lexical" class="box">Fetching next source</span></div>'
                )
            """)
            remounted = {item["kind"]: item["digest"] for item in (await _snapshot(page, monkeypatch))["progressBlocks"]}
            assert remounted["dom-tool-result"] == structural_changed["dom-tool-result"]
            assert remounted["fetching"] == lexical_changed["fetching"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_exact_candidate_budget_allows_trailing_dom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            candidates = "".join(f'<div class="box" role="status">state-{i}</div>' for i in range(256))
            await page.set_content(_BASE + f'<div class="agent-turn">{candidates}<div class="box">ordinary trailing DOM</div></div>')
            assert len((await _snapshot(page, monkeypatch))["progressBlocks"]) == 128
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_candidate_257_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            candidates = "".join(f'<div class="box" role="status">state-{i}</div>' for i in range(257))
            await page.set_content(_BASE + f'<div class="agent-turn">{candidates}</div>')
            assert (await _snapshot(page, monkeypatch))["progressBlocks"] == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_oversized_text_region_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            text_nodes = "".join(f"<span>{'X' * 10000}</span>" for _ in range(257))
            await page.set_content(_BASE + f'<div class="agent-turn"><div data-testid="tool-result">{text_nodes}</div></div>')
            snapshot = await _snapshot(page, monkeypatch)
            assert snapshot["progressBlocks"] == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_oversized_semantic_region_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            nodes = "".join(f'<span data-phase="phase-{index}"></span>' for index in range(257))
            await page.set_content(_BASE + f'<div class="agent-turn"><div data-testid="tool-result">{nodes}</div></div>')
            snapshot = await _snapshot(page, monkeypatch)
            assert snapshot["progressBlocks"] == []
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
            huge = "R" * 12000
            await page.set_content(_BASE + f'<div class="agent-turn"><div id="region" data-testid="tool-result" aria-label="{huge}">{huge}{children}</div></div>')
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


@pytest.mark.asyncio
async def test_structural_progress_is_newest_first_and_history_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            turns = "".join(
                f'<div data-message-author-role="user" data-message-id="p-{i}">P{i}</div>'
                f'<div class="agent-turn"><div class="box" role="status">state-{i}</div></div>'
                for i in range(12)
            )
            await page.set_content(_BASE + turns)
            snapshot = await _snapshot(page, monkeypatch)
            assert [item["ownerPromptMessageId"] for item in snapshot["progressBlocks"]] == [
                "p-11", "p-10", "p-9", "p-8", "p-7", "p-6", "p-5", "p-4"
            ]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_excessive_visible_nodes_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            filler = "".join('<div class="box"></div>' for _ in range(2050))
            await page.set_content(_BASE + f'<div class="agent-turn">{filler}<div class="box" role="status">late</div></div>')
            snapshot = await _snapshot(page, monkeypatch)
            assert snapshot["progressBlocks"] == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_owner_lookup_fails_closed_outside_bounded_user_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            later_users = "".join(
                f'<div data-message-author-role="user" data-message-id="later-{i}">later</div>'
                for i in range(40)
            )
            await page.set_content(_BASE + '<div class="agent-turn"><div class="box" role="status">working</div></div>' + later_users)
            assert (await _snapshot(page, monkeypatch))["progressBlocks"] == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_progress_visibility_fails_closed_above_ancestor_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            nested = '<div>' * 65 + '<div class="box" role="status">working</div>' + '</div>' * 65
            await page.set_content(_BASE + f'<div class="agent-turn">{nested}</div>')
            assert (await _snapshot(page, monkeypatch))["progressBlocks"] == []
        finally:
            await browser.close()
