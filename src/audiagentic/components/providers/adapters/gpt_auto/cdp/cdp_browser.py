"""Typed generic browser controller built on the Chrome DevTools Protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .bridge import PythonCdpBridge


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class CdpPageRef:
    handle: str
    target_id: str
    window_id: int | None = None
    url: str = ""
    title: str = ""

    def __post_init__(self) -> None:
        _required(self.handle, "page handle")
        _required(self.target_id, "target id")


@dataclass(frozen=True)
class CdpWindowBounds:
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None
    window_state: str | None = None

    def as_cdp(self) -> dict[str, Any]:
        values = {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "windowState": self.window_state,
        }
        return {key: value for key, value in values.items() if value is not None}


class CdpBrowserController:
    """Provider-neutral typed browser operations over CDP."""

    def __init__(self, bridge: PythonCdpBridge) -> None:
        self.bridge = bridge

    async def browser_info(self) -> dict[str, Any]:
        return await self.bridge.call("browser_info")

    async def pages(self) -> tuple[CdpPageRef, ...]:
        raw = await self.bridge.call("list_pages")
        return tuple(
            CdpPageRef(
                str(i["pageHandle"]),
                str(i["targetId"]),
                i.get("windowId"),
                str(i.get("url") or ""),
                str(i.get("title") or ""),
            )
            for i in raw
        )

    async def page_by_handle(self, handle: str) -> CdpPageRef:
        for page in await self.pages():
            if page.handle == handle:
                return page
        raise RuntimeError(f"unknown or closed page handle: {handle}")

    async def page(self, handle: str) -> CdpPageRef:
        return await self.page_by_handle(handle)

    async def new_window(self) -> CdpPageRef:
        return await self._page(await self.bridge.call("create_window_page"))

    async def new_tab(self, *, in_window: CdpPageRef | None = None) -> CdpPageRef:
        result = (
            await self.bridge.call("create_page")
            if in_window is None
            else await self.bridge.call(
                "create_page_in_window", {"anchorPageHandle": self._handle(in_window)}
            )
        )
        return await self._page(result)

    async def close(self, page: CdpPageRef) -> None:
        await self.bridge.call("close_page", {"pageHandle": self._handle(page)})

    async def navigate(self, page: CdpPageRef, url: str) -> CdpPageRef:
        url = _required(url, "url")
        if not urlparse(url).scheme:
            raise ValueError("url must include a scheme")
        await self.bridge.call("navigate", {"pageHandle": self._handle(page), "url": url})
        return CdpPageRef(page.handle, page.target_id, page.window_id, url, page.title)

    async def evaluate(self, page: CdpPageRef, function: str, argument: Any = None) -> Any:
        return await self.bridge.evaluate(self._handle(page), function, argument)

    async def activate(self, page: CdpPageRef) -> None:
        await self.bridge.call("activate_target", {"pageHandle": self._handle(page)})

    async def bounds(self, page: CdpPageRef) -> CdpWindowBounds:
        raw = await self.bridge.call("window_bounds", {"pageHandle": self._handle(page)})
        value = raw.get("bounds", raw)
        return CdpWindowBounds(
            value.get("left"),
            value.get("top"),
            value.get("width"),
            value.get("height"),
            value.get("windowState"),
        )

    async def set_bounds(self, page: CdpPageRef, bounds: CdpWindowBounds) -> None:
        await self.bridge.call(
            "set_window_bounds", {"pageHandle": self._handle(page), "bounds": bounds.as_cdp()}
        )

    async def _page(self, value: Mapping[str, Any]) -> CdpPageRef:
        return CdpPageRef(
            str(value["pageHandle"]),
            str(value["targetId"]),
            value.get("windowId"),
            str(value.get("url") or ""),
            str(value.get("title") or ""),
        )

    @staticmethod
    def _handle(page: CdpPageRef) -> str:
        if not isinstance(page, CdpPageRef):
            raise TypeError("expected CdpPageRef")
        return page.handle
