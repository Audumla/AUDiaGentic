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
        # GP42: this is called on every poll tick of every open
        # conversation. Routing it through pages() (a full
        # Target.getTargets scan of the ENTIRE shared browser) turned
        # every poll of every gpt-auto tab into a browser-wide scan
        # several times a second. get_page resolves only this one
        # already-known target.
        value = await self.bridge.call("get_page", {"pageHandle": handle})
        return CdpPageRef(
            str(value["pageHandle"]),
            str(value["targetId"]),
            value.get("windowId"),
            str(value.get("url") or ""),
            str(value.get("title") or ""),
        )

    async def page(self, handle: str) -> CdpPageRef:
        return await self.page_by_handle(handle)

    async def new_window(self) -> CdpPageRef:
        return await self._page(await self.bridge.call("create_window_page"))

    async def new_tab(
        self,
        *,
        in_window: CdpPageRef | None = None,
        url: str | None = None,
    ) -> CdpPageRef:
        if url is not None:
            url = _required(url, "url")
            if not urlparse(url).scheme:
                raise ValueError("url must include a scheme")
        result = (
            await self.bridge.call("create_page")
            if in_window is None
            else await self.bridge.call(
                "create_page_in_window",
                {
                    "anchorPageHandle": self._handle(in_window),
                    **({"url": url} if url is not None else {}),
                },
            )
        )
        page = await self._page(result)
        if url is not None and in_window is None:
            return await self.navigate(page, url)
        return page

    async def close(self, page: CdpPageRef) -> None:
        await self.bridge.call("close_page", {"pageHandle": self._handle(page)})

    async def insert_text(self, page: CdpPageRef, text: str) -> None:
        if not isinstance(text, str) or not text:
            raise ValueError("text must be a non-empty string")
        await self.bridge.call(
            "insert_text", {"pageHandle": self._handle(page), "text": text}
        )

    async def navigate(self, page: CdpPageRef, url: str) -> CdpPageRef:
        url = _required(url, "url")
        if not urlparse(url).scheme:
            raise ValueError("url must include a scheme")
        await self.bridge.call("navigate", {"pageHandle": self._handle(page), "url": url})
        return CdpPageRef(page.handle, page.target_id, page.window_id, url, page.title)

    async def evaluate(self, page: CdpPageRef, function: str, argument: Any = None) -> Any:
        return await self.bridge.evaluate(self._handle(page), function, argument)

    async def hover_text(self, page: CdpPageRef, label: str) -> bool:
        """Move the native CDP pointer over the visible exact-label control."""
        point = await self._text_point(page, label)
        if point is None:
            return False
        await self.bridge.call(
            "hover",
            {"pageHandle": self._handle(page), "x": point["x"], "y": point["y"]},
        )
        return True

    async def click_text(self, page: CdpPageRef, label: str) -> bool:
        """Press and release the native CDP pointer on an exact-label element."""
        point = await self._text_point(page, label)
        if point is None:
            return False
        await self.bridge.call(
            "click",
            {"pageHandle": self._handle(page), "x": point["x"], "y": point["y"]},
        )
        return True

    async def _text_point(self, page: CdpPageRef, label: str) -> dict[str, float] | None:
        """Resolve an exact visible text/ARIA label to viewport coordinates."""
        point = await self.evaluate(
            page,
            r"""(wantedLabel) => {
              const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
              const wanted = normalize(wantedLabel);
              const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                return rect.width > 0 && rect.height > 0 &&
                  style.display !== 'none' && style.visibility !== 'hidden' &&
                  style.opacity !== '0';
              };
              const label = element => normalize(
                element.getAttribute('aria-label') || element.innerText ||
                element.textContent || element.getAttribute('title')
              );
              const node = Array.from(document.querySelectorAll('*')).find(
                candidate => visible(candidate) && label(candidate) === wanted
              );
              if (!node) return null;
              node.scrollIntoView({block: 'center', inline: 'nearest'});
              const rect = node.getBoundingClientRect();
              return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
            }""",
            label,
        )
        if not isinstance(point, dict):
            return None
        x = point.get("x")
        y = point.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return {"x": float(x), "y": float(y)}

    async def activate(self, page: CdpPageRef) -> None:
        await self.bridge.call("activate_target", {"pageHandle": self._handle(page)})

    async def press_enter(self, page: CdpPageRef) -> None:
        await self.bridge.call("press_enter", {"pageHandle": self._handle(page)})

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
