"""Executable DOM coverage for project identity discovery on /projects."""

from __future__ import annotations

import pytest
from playwright.async_api import Error as PlaywrightError, async_playwright

from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
    _PROJECT_NEW_CHAT_POINT_FN,
)


_PROJECT_ID = "g-p-69cc8c4cc7648191a009f358113d8dd2"
_OTHER_PROJECT_ID = "g-p-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _markup(sidebar_ids: list[str]) -> str:
    sidebar = "".join(
        f'<div data-app-action-sidebar-project-row="" '
        f'data-app-action-sidebar-project-label="AUDiaGentic" '
        f'data-app-action-sidebar-project-id="{project_id}" '
        f'style="display:block;width:100px;height:20px"></div>'
        for project_id in sidebar_ids
    )
    return f"""
        <style>
          [data-project-row="true"] {{ display: block; width: 600px; height: 70px; }}
          [data-project-row="true"] button {{ display: block; width: 32px; height: 32px; }}
        </style>
        <aside id="sidebar">{sidebar}</aside>
        <div data-project-row="true">
          <span>AUDiaGentic</span>
          <button aria-label="Start new chat in project"></button>
        </div>
    """


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sidebar_ids", "expected_id", "project_id"),
    [
        ([_PROJECT_ID], "", _PROJECT_ID),
        ([], "", None),
        ([_PROJECT_ID, _OTHER_PROJECT_ID], "", None),
        ([_PROJECT_ID, _OTHER_PROJECT_ID], _PROJECT_ID, _PROJECT_ID),
        ([_OTHER_PROJECT_ID], _PROJECT_ID, None),
    ],
    ids=["unique", "missing", "ambiguous", "configured-disambiguation", "configured-miss"],
)
async def test_projects_selector_proves_identity_from_sidebar_dom(
    sidebar_ids: list[str], expected_id: str, project_id: str | None
) -> None:
    """The selector must execute against the DOM rather than source-string mocks."""
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except PlaywrightError as error:
            pytest.skip(f"headless Chromium unavailable: {error}")
        try:
            page = await browser.new_page(viewport={"width": 1200, "height": 900})
            await page.set_content(_markup(sidebar_ids))
            result = await page.evaluate(
                _PROJECT_NEW_CHAT_POINT_FN,
                {"name": "AUDiaGentic", "expectedProjectId": expected_id},
            )
            if project_id is None:
                assert result is None
            else:
                assert result["projectId"] == project_id
                assert isinstance(result["x"], (int, float))
                assert isinstance(result["y"], (int, float))
        finally:
            await browser.close()