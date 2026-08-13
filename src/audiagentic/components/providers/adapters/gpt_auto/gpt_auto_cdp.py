"""GPT-auto extensions over the generic CDP browser controller."""

from __future__ import annotations

from typing import Any

from .cdp.cdp_browser import CdpBrowserController, CdpPageRef, CdpWindowBounds


class GptAutoCdpBrowserController(CdpBrowserController):
    """ChatGPT-specific operations over the generic CDP controller."""

    async def wait_for_composer(self, page: CdpPageRef, *, timeout: float) -> dict[str, Any]:
        return await self.bridge.wait_for_composer(self._handle(page), timeout=timeout)

    async def submit(
        self, page: CdpPageRef, text: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        return await self.bridge.submit_prompt_verified(self._handle(page), text, timeout=timeout)


__all__ = ["GptAutoCdpBrowserController", "CdpPageRef", "CdpWindowBounds"]
