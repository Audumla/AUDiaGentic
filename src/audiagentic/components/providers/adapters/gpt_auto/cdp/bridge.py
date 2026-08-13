"""Provider-neutral browser operations implemented over Python CDP."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from ..config import GptAutoConfig
from .client import CdpClient


@dataclass(frozen=True)
class BridgeEvent:
    name: str
    page_handle: str | None = None
    payload: dict[str, Any] | None = None


class PythonCdpBridge:
    """Generic CDP transport and page/window lifecycle façade."""

    def __init__(self, config: GptAutoConfig) -> None:
        self.config = config
        self._client: CdpClient | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pages: dict[str, str] = {}
        self._sessions: dict[str, str] = {}
        self._next_page = 1
        self._tab_open_lock = asyncio.Lock()
        self.events: asyncio.Queue[BridgeEvent] = asyncio.Queue()

    @property
    def client(self) -> CdpClient:
        if self._client is None:
            raise RuntimeError("Python CDP bridge is not running")
        return self._client

    async def start(self, *, connect_timeout: float | None = None) -> None:
        if self._client is not None:
            return
        client = CdpClient(
            self.config.cdp_url,
            default_timeout=self.config.cdp.protocol_timeout_seconds,
            connect_timeout=connect_timeout or self.config.cdp.connect_timeout_seconds,
            devtools_active_port_file=self.config.cdp.devtools_active_port_file,
        )
        await client.start()
        self._client = client
        self._reader_task = asyncio.create_task(self._route_events(client))
        await client.command("Target.setDiscoverTargets", {"discover": True})
        await self._refresh_pages()

    async def _route_events(self, client: CdpClient) -> None:
        while self._client is client:
            event = await client.events.get()
            target_id = str(event.params.get("targetId") or "")
            if not target_id and event.session_id:
                target_id = next(
                    (t for t, s in self._sessions.items() if s == event.session_id), ""
                )
            handle = next((h for h, target in self._pages.items() if target == target_id), None)
            if event.method == "cdp.disconnected":
                await self.events.put(BridgeEvent("browser_disconnected"))
            elif event.method in {"Target.targetDestroyed", "Target.targetCrashed"} and handle:
                await self.events.put(
                    BridgeEvent(
                        "page_closed" if event.method.endswith("Destroyed") else "page_crashed",
                        handle,
                        event.params,
                    )
                )
                self._pages.pop(handle, None)
                self._sessions.pop(target_id, None)
            elif event.method == "Target.targetCreated":
                await self.events.put(BridgeEvent("target_created", handle, event.params))
            elif event.method == "Target.targetInfoChanged":
                await self.events.put(BridgeEvent("target_changed", handle, event.params))
            elif event.method in {
                "Page.lifecycleEvent",
                "Page.loadEventFired",
                "Page.domContentEventFired",
            }:
                await self.events.put(BridgeEvent("page_lifecycle", handle, event.params))
            elif event.method == "Target.detachedFromTarget" and handle:
                self._sessions.pop(target_id, None)

    async def _refresh_pages(self) -> list[dict[str, Any]]:
        targets = await self.client.command("Target.getTargets")
        result = []
        for info in targets.get("targetInfos", []):
            if info.get("type") != "page":
                continue
            target_id = str(info["targetId"])
            handle = self._handle_for_target(target_id)
            result.append(
                {
                    "pageHandle": handle,
                    "url": str(info.get("url") or ""),
                    "title": str(info.get("title") or ""),
                    "targetId": target_id,
                    "windowId": await self._window_id(target_id),
                }
            )
        return result

    def _handle_for_target(self, target_id: str) -> str:
        """Return one stable handle per physical CDP target."""
        existing = next((h for h, value in self._pages.items() if value == target_id), None)
        if existing is not None:
            return existing
        handle = f"page-{self._next_page}"
        self._next_page += 1
        self._pages[handle] = target_id
        return handle

    async def _window_id(self, target_id: str) -> int | None:
        result = await self.client.command("Browser.getWindowForTarget", {"targetId": target_id})
        return int(result["windowId"]) if result.get("windowId") is not None else None

    async def _target(self, handle: str) -> str:
        try:
            return self._pages[handle]
        except KeyError as exc:
            raise RuntimeError(f"unknown or closed page handle: {handle}") from exc

    async def _session(self, handle: str) -> str:
        target_id = await self._target(handle)
        if target_id in self._sessions:
            return self._sessions[target_id]
        result = await self.client.command(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        session = str(result["sessionId"])
        try:
            await self.client.command("Page.enable", session_id=session)
            await self.client.command(
                "Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=session
            )
        except BaseException:
            self._sessions.pop(target_id, None)
            raise
        self._sessions[target_id] = session
        return session

    async def evaluate(
        self, page_handle: str, function: str, argument: Any = None, *, user_gesture: bool = False
    ) -> Any:
        session = await self._session(page_handle)
        expression = f"({function})({json.dumps(argument, separators=(',', ':'))})"
        result = await self.client.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": user_gesture,
            },
            session_id=session,
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(str(result["exceptionDetails"]))
        return (result.get("result") or {}).get("value")

    async def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        params = params or {}
        if method == "browser_info":
            return await self.client.command("Browser.getVersion", timeout=timeout)
        if method == "list_pages":
            return await self._refresh_pages()
        if method in {"create_page", "create_window_page"}:
            async with self._tab_open_lock:
                result = await self.client.command(
                    "Target.createTarget",
                    {
                        "url": "about:blank",
                        "background": True,
                        "newWindow": method == "create_window_page",
                    },
                    timeout=timeout,
                )
                target_id = str(result["targetId"])
                handle = self._handle_for_target(target_id)
                return {
                    "pageHandle": handle,
                    "targetId": target_id,
                    "windowId": await self._window_id(target_id),
                }
        if method == "create_page_in_window":
            async with self._tab_open_lock:
                anchor = str(params["anchorPageHandle"])
                anchor_target = await self._target(anchor)
                before = {
                    str(i["targetId"])
                    for i in (await self.client.command("Target.getTargets")).get("targetInfos", [])
                }
                await self.evaluate(
                    anchor,
                    "() => { window.open('about:blank', '_blank'); return true; }",
                    user_gesture=True,
                )
                deadline = asyncio.get_running_loop().time() + (timeout or 5.0)
                target_id = None
                while asyncio.get_running_loop().time() < deadline:
                    for info in (await self.client.command("Target.getTargets")).get(
                        "targetInfos", []
                    ):
                        candidate = str(info.get("targetId") or "")
                        if (
                            candidate not in before
                            and info.get("type") == "page"
                            and str(info.get("openerId") or "") == anchor_target
                        ):
                            target_id = candidate
                            break
                    if target_id:
                        break
                    await asyncio.sleep(0.05)
                if target_id is None:
                    raise RuntimeError("window.open did not create a page target")
                handle = self._handle_for_target(target_id)
                return {
                    "pageHandle": handle,
                    "targetId": target_id,
                    "windowId": await self._window_id(target_id),
                }
        handle = str(params.get("pageHandle") or "")
        if method == "close_page":
            target_id = await self._target(handle)
            await self.client.command(
                "Target.closeTarget", {"targetId": target_id}, timeout=timeout
            )
            self._pages.pop(handle, None)
            self._sessions.pop(target_id, None)
            return {"closed": True}
        if method == "window_id":
            return {"windowId": await self._window_id(await self._target(handle))}
        if method == "window_bounds":
            window_id = params.get("windowId") or await self._window_id(await self._target(handle))
            return await self.client.command(
                "Browser.getWindowBounds", {"windowId": window_id}, timeout=timeout
            )
        if method == "set_window_bounds":
            window_id = params.get("windowId") or await self._window_id(await self._target(handle))
            return await self.client.command(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": dict(params["bounds"])},
                timeout=timeout,
            )
        if method == "target_info":
            return await self.client.command(
                "Target.getTargetInfo", {"targetId": await self._target(handle)}, timeout=timeout
            )
        if method == "activate_target":
            return await self.client.command(
                "Target.activateTarget", {"targetId": await self._target(handle)}, timeout=timeout
            )
        session = await self._session(handle)
        if method == "navigate":
            result = await self.client.command(
                "Page.navigate", {"url": params["url"]}, session_id=session, timeout=timeout
            )
            if result.get("errorText"):
                raise RuntimeError(str(result["errorText"]))
            return {"url": str(params["url"])}
        if method == "keep_page_active":
            await self.client.command("Page.bringToFront", session_id=session)
            await self.evaluate(handle, "() => { window.focus(); return true; }")
            return {"ok": True}
        if method == "dispatch_enter":
            for event_type in ("keyDown", "keyUp"):
                await self.client.command(
                    "Input.dispatchKeyEvent",
                    {
                        "type": event_type,
                        "key": "Enter",
                        "code": "Enter",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                    },
                    session_id=session,
                )
            return {"ok": True}
        raise RuntimeError(f"unknown bridge method: {method}")

    async def stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.stop()
        task, self._reader_task = self._reader_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._pages.clear()
        self._sessions.clear()
