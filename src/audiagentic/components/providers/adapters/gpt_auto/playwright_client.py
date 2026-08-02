"""Playwright client for browser automation.

Launches a persistent Chrome instance with a local profile directory so
ChatGPT login cookies survive between runs.  Provides tab enumeration,
typing, key presses, and DOM evaluation against the active ChatGPT page.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TabInfo:
    """Metadata about a browser tab."""

    index: int
    url: str
    title: str


# ---------------------------------------------------------------------------
# Browser detection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectedBrowser:
    """Result of browser auto-detection."""

    name: str
    path: Path


def detect_chromium_browser() -> DetectedBrowser | None:
    """Find an installed Chromium-based browser on the current platform.

    Checks common installation locations in priority order and returns the
    first executable found.  Returns ``None`` if no Chromium browser is
    detected.
    """
    system = platform.system()

    if system == "Windows":
        candidates: list[tuple[str, tuple[str, ...]]] = [
            ("Chrome", (
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            )),
            ("Edge", (
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            )),
            ("Brave", (
                r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
            )),
        ]
    elif system == "Darwin":
        candidates = [
            ("Chrome", (
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            )),
            ("Edge", (
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            )),
            ("Brave", (
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            )),
        ]
    else:  # Linux
        candidates = [
            ("Chrome", (
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/snap/bin/chromium",
                "/usr/bin/chromium-browser",
            )),
            ("Edge", (
                "/usr/bin/microsoft-edge",
            )),
            ("Brave", (
                "/usr/bin/brave-browser",
                "/usr/bin/brave-browser-stable",
            )),
        ]

    for name, paths in candidates:
        for raw_path in paths:
            resolved = Path(os.path.expandvars(raw_path)).expanduser()
            if resolved.exists() and os.access(resolved, os.X_OK):
                logger.info("Detected %s at %s", name, resolved)
                return DetectedBrowser(name=name, path=resolved)

    return None


# ---------------------------------------------------------------------------
# Playwright client
# ---------------------------------------------------------------------------


class PlaywrightClient:
    """Manages a persistent Chrome instance with a local profile directory.

    The profile directory stores cookies so the user only needs to log in
    to ChatGPT once — subsequent runs reuse the authenticated session.
    """

    def __init__(
        self,
        target_url: str = "https://chat.openai.com",
        profile_dir: str | None = None,
        browser_path: str | None = None,
    ) -> None:
        self._target_url = target_url
        self._profile_dir = profile_dir or "~/.gpt-auto-profile"
        self._browser_path = browser_path
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # -- lifecycle -----------------------------------------------------------------

    async def start(self) -> None:
        """Launch Chrome with a persistent profile and open the target URL."""
        pw = await async_playwright().start()
        browser_type = pw.chromium

        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "slow_mo": 50,
        }
        if self._browser_path is not None:
            launch_kwargs["executable_path"] = self._browser_path

        self._context = await browser_type.launch_persistent_context(
            user_data_dir=self._profile_dir,
            **launch_kwargs,
        )

        # Open ChatGPT in the first tab
        ctx = self._context
        assert ctx is not None, "context not initialized"
        pages = ctx.pages
        if pages:
            self._page = pages[0]
        else:
            self._page = await ctx.new_page()

        pg = self._page
        assert pg is not None, "no page available"
        logger.info("Navigating to %s", self._target_url)
        await pg.goto(self._target_url, wait_until="domcontentloaded")

    async def stop(self) -> None:
        """Close the browser and release resources."""
        if self._context is not None:
            logger.info("Closing Playwright context")
            await self._context.close()
            self._context = None
            self._page = None

    # -- page access ----------------------------------------------------------------

    @property
    def page(self) -> Page | None:
        """Currently active page (may be None before start / after stop)."""
        return self._page

    @page.setter
    def page(self, value: Page) -> None:
        self._page = value

    # -- tab operations ------------------------------------------------------------

    async def list_tabs(self) -> list[TabInfo]:
        """Return all open pages in the context."""
        if self._context is None:
            return []

        tabs: list[TabInfo] = []
        for idx, pg in enumerate(self._context.pages):
            try:
                url = await pg.url
                title = await pg.title()
            except Exception as exc:
                logger.debug("Could not read tab %d: %s", idx, exc)
                continue
            tabs.append(TabInfo(index=idx, url=url, title=title))

        logger.debug("Found %d tab(s)", len(tabs))
        return tabs

    async def find_chatgpt_tab(self) -> Page | None:
        """Return the first page whose URL contains the target hostname."""
        for pg in self._context.pages if self._context else []:
            try:
                url = await pg.url
            except Exception:
                continue
            if "chat.openai.com" in url.lower() or "openai" in url.lower():
                return pg
        return None

    # -- typing --------------------------------------------------------------------

    async def type_text(self, text: str, delay: float = 0.02) -> None:
        """Type *text* character-by-character into the currently focused element.

        ``delay`` is in seconds between keystrokes — use a small value for
        human-like typing speed.
        """
        if self._page is None:
            raise RuntimeError("No active page")
        await self._page.keyboard.type(text, delay=delay * 1000)

    async def press_key(self, key: str = "Enter") -> None:
        """Press a single key on the focused page."""
        if self._page is None:
            raise RuntimeError("No active page")
        await self._page.keyboard.press(key)

    # -- DOM evaluation ------------------------------------------------------------

    async def evaluate(self, script: str) -> Any:
        """Execute JavaScript on the currently focused page and return the result."""
        if self._page is None:
            raise RuntimeError("No active page")
        try:
            return await self._page.evaluate(script)
        except Exception as exc:
            logger.warning("evaluate() failed: %s", exc)
            return None

    # -- waiting -------------------------------------------------------------------

    async def wait_for_selector(
        self,
        selector: str,
        timeout: float = 5000.0,
    ) -> bool:
        """Wait for an element matching *selector* to appear on the page.

        Returns ``True`` if found within *timeout*, ``False`` otherwise.
        """
        if self._page is None:
            raise RuntimeError("No active page")
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception as exc:
            logger.debug("wait_for_selector(%s) timed out: %s", selector, exc)
            return False

    async def wait_for_url(
        self,
        pattern: str,
        timeout: float = 10000.0,
    ) -> bool:
        """Wait for the page URL to match *pattern* (substring)."""
        if self._page is None:
            raise RuntimeError("No active page")
        try:
            await self._page.wait_for_url(pattern, timeout=timeout)
            return True
        except Exception as exc:
            logger.debug("wait_for_url(%s) timed out: %s", pattern, exc)
            return False

    # -- utility -------------------------------------------------------------------

    async def screenshot(self, path: str | None = None) -> bytes | None:
        """Take a screenshot of the current page.

        If *path* is given, saves the file and returns ``None``; otherwise
        returns raw PNG bytes.
        """
        if self._page is None:
            return None
        if path is not None:
            await self._page.screenshot(path=path)
            return None
        return await self._page.screenshot()
