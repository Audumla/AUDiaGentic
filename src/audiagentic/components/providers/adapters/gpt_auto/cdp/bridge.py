"""Provider-neutral browser operations implemented over Python CDP."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from ..config import GptAutoConfig
from .client import CdpClient, CdpError, CdpStaleGenerationError


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
        # GP18: the underlying CdpClient can silently reconnect (a fresh
        # WebSocket connection) when it detects its previous connection is
        # stale. Target-attachment sessionIds are scoped to the specific
        # connection they were established on, so a session cached from
        # before a reconnect is invalid on the new one (CDP error -32001
        # "Session with given id not found."). Track the client's
        # connection generation and invalidate the session cache -- not
        # the page/target-handle map, target identity itself survives a
        # client reconnect -- whenever it changes.
        self._known_connection_generation: int | None = None
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
        self._known_connection_generation = client.connection_generation
        self._reader_task = asyncio.create_task(self._route_events(client))
        await client.command("Target.setDiscoverTargets", {"discover": True})
        await self._refresh_pages()

    def _generation(self) -> int:
        # getattr fallback keeps small adapter test doubles compatible while
        # the production CdpClient always supplies connection_generation.
        return getattr(self.client, "connection_generation", 0)

    async def _invalidate_stale_sessions_if_reconnected(self) -> None:
        current_generation = self._generation()
        if self._known_connection_generation == current_generation:
            return
        self._sessions.clear()
        self._known_connection_generation = current_generation
        # GP18 review follow-up: a fresh WebSocket connection loses
        # browser-level, connection-scoped setup. Target.* attachment is
        # re-established per _session() call (session-scoped), but target
        # discovery is a one-time subscription per CONNECTION -- without
        # re-issuing it here, target-created/destroyed/crashed events
        # silently stop arriving after a transparent reconnect even though
        # ordinary commands keep working.
        try:
            await self.client.command("Target.setDiscoverTargets", {"discover": True})
        except CdpError:
            pass

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
            try:
                window_id = await self._window_id(target_id)
            except CdpError:
                # A target that isn't a real tabbed browser window (e.g. a
                # devtools:// inspector page opened by the operator) has no
                # window to resolve. One such target must not abort page
                # enumeration for every other live page on the shared
                # browser -- treat it as windowless and keep going.
                window_id = None
            result.append(
                {
                    "pageHandle": handle,
                    "url": str(info.get("url") or ""),
                    "title": str(info.get("title") or ""),
                    "targetId": target_id,
                    "windowId": window_id,
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

    async def _session(self, handle: str) -> tuple[str, int]:
        """Return a (session_id, connection_generation) pair.

        GP18 review follow-up: the generation is the connection generation
        the session is valid for, captured atomically with the attach
        sequence (retried whole if a reconnect invalidates a
        just-attached session mid-setup). Callers must pass this
        generation as required_generation on any later command() using
        this session_id, since a reconnect can happen in the gap between
        this call returning and that later command actually sending.
        """
        await self._invalidate_stale_sessions_if_reconnected()
        target_id = await self._target(handle)
        if target_id in self._sessions:
            return self._sessions[target_id], self._generation()
        while True:
            result = await self.client.command(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
            session = str(result["sessionId"])
            generation = self._generation()
            try:
                await self.client.command(
                    "Page.enable", session_id=session, required_generation=generation
                )
                await self.client.command(
                    "Page.setLifecycleEventsEnabled",
                    {"enabled": True},
                    session_id=session,
                    required_generation=generation,
                )
            except CdpStaleGenerationError:
                # Reconnected between attach and setup -- the session we
                # just attached is already invalid on the new connection.
                # Retry the whole attach sequence fresh rather than send
                # setup commands for a session that can never work.
                continue
            except BaseException:
                self._sessions.pop(target_id, None)
                raise
            self._sessions[target_id] = session
            return session, generation

    async def _session_command(
        self,
        handle: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Run a session-scoped command, retrying once if a reconnect
        invalidated the session between fetch and send (GP18 review:
        closes the TOCTOU race a plain `session = await self._session(...)`
        followed later by `client.command(..., session_id=session)` has)."""
        session, generation = await self._session(handle)
        try:
            return await self.client.command(
                method, params, session_id=session, timeout=timeout, required_generation=generation
            )
        except CdpStaleGenerationError:
            session, generation = await self._session(handle)
            return await self.client.command(
                method, params, session_id=session, timeout=timeout, required_generation=generation
            )

    async def evaluate(
        self, page_handle: str, function: str, argument: Any = None, *, user_gesture: bool = False
    ) -> Any:
        expression = f"({function})({json.dumps(argument, separators=(',', ':'))})"
        result = await self._session_command(
            page_handle,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": user_gesture,
            },
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
        if method == "navigate":
            result = await self._session_command(
                handle, "Page.navigate", {"url": params["url"]}, timeout=timeout
            )
            if result.get("errorText"):
                raise RuntimeError(str(result["errorText"]))
            return {"url": str(params["url"])}
        if method == "keep_page_active":
            await self._session_command(handle, "Page.bringToFront")
            await self.evaluate(handle, "() => { window.focus(); return true; }")
            return {"ok": True}
        if method == "dispatch_enter":
            for event_type in ("keyDown", "keyUp"):
                await self._session_command(
                    handle,
                    "Input.dispatchKeyEvent",
                    {
                        "type": event_type,
                        "key": "Enter",
                        "code": "Enter",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                    },
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
