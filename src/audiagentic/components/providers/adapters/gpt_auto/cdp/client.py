"""Minimal asyncio CDP transport.

This deliberately implements only the protocol plumbing.  Browser-specific
operations belong in :mod:`bridge`, which keeps the client reusable for other
browser-backed providers later.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from dataclasses import dataclass
from typing import Any

try:
    from websockets.asyncio.client import ClientConnection, connect
except ImportError:  # websockets < 14
    from websockets import connect
    from websockets.client import WebSocketClientProtocol as ClientConnection


class CdpError(RuntimeError):
    """A CDP command returned an error."""


@dataclass(frozen=True)
class CdpEvent:
    method: str
    params: dict[str, Any]
    session_id: str | None = None


class CdpClient:
    """Multiplex commands and events over one browser-level CDP socket."""

    def __init__(
        self,
        endpoint: str,
        *,
        default_timeout: float = 30.0,
        connect_timeout: float | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.default_timeout = default_timeout
        self.connect_timeout = connect_timeout or default_timeout
        self._socket: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self.events: asyncio.Queue[CdpEvent] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._stopping = False

    async def start(self) -> None:
        if self._socket is not None:
            return
        self._stopping = False
        websocket_url = await asyncio.to_thread(
            self._discover_websocket_url, self.connect_timeout
        )
        self._socket = await connect(
            websocket_url, max_size=None, open_timeout=self.connect_timeout
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    def _discover_websocket_url(self, timeout: float | None = None) -> str:
        if self.endpoint.startswith(("ws://", "wss://")):
            return self.endpoint
        url = self.endpoint + "/json/version"
        with urllib.request.urlopen(url, timeout=timeout or self.default_timeout) as response:
            payload = json.load(response)
        value = payload.get("webSocketDebuggerUrl")
        if not isinstance(value, str) or not value:
            raise CdpError("CDP /json/version did not provide webSocketDebuggerUrl")
        return value

    async def command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        socket = self._socket
        if socket is None:
            raise CdpError("CDP client is not connected")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message: dict[str, Any] = {"id": request_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        try:
            async with self._send_lock:
                await socket.send(json.dumps(message, separators=(",", ":")))
            return await asyncio.wait_for(future, timeout or self.default_timeout)
        finally:
            self._pending.pop(request_id, None)

    async def _read_loop(self) -> None:
        socket = self._socket
        if socket is None:
            return
        failure: Exception | None = None
        try:
            async for raw in socket:
                value = json.loads(raw)
                if "id" in value:
                    future = self._pending.get(int(value["id"]))
                    if future is None or future.done():
                        continue
                    if "error" in value:
                        error = value["error"]
                        future.set_exception(CdpError(str(error)))
                    else:
                        future.set_result(value.get("result"))
                elif "method" in value:
                    await self.events.put(
                        CdpEvent(
                            str(value["method"]),
                            dict(value.get("params") or {}),
                            str(value["sessionId"]) if value.get("sessionId") else None,
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail all in-flight commands
            failure = exc
        finally:
            # A clean WebSocket iterator exit is still a connection loss. Do
            # this in one place so pending calls never silently time out.
            if not self._stopping:
                error = CdpError(f"CDP connection closed: {failure or 'socket closed'}")
                for future in tuple(self._pending.values()):
                    if not future.done():
                        future.set_exception(error)
                await self.events.put(CdpEvent("cdp.disconnected", {"error": str(error)}))

    async def stop(self) -> None:
        self._stopping = True
        socket, self._socket = self._socket, None
        if socket is not None:
            await socket.close()
        task, self._reader_task = self._reader_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        error = CdpError("CDP client stopped")
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
