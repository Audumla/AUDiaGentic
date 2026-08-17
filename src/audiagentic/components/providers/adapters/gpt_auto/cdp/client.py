"""Minimal asyncio CDP transport.

This deliberately implements only the protocol plumbing.  Browser-specific
operations belong in :mod:`bridge`, which keeps the client reusable for other
browser-backed providers later.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from websockets.asyncio.client import ClientConnection, connect
except ImportError:  # websockets < 14
    from websockets import connect
    from websockets.client import WebSocketClientProtocol as ClientConnection


# TEMPORARY GP18 debug instrumentation -- tests the event-loop-ownership
# hypothesis (the singleton CdpClient's reader task may outlive the asyncio
# event loop of the pytest test that created it, becoming pending-forever
# rather than dead once a later test's loop tries to reuse it). Writes
# directly to disk since the gateway subprocess's stdout/stderr are
# discarded and no log file handler is configured. Remove once GP18's
# mechanism is confirmed or ruled out.
_GP18_TRACE_PATH = r"C:\Users\mgs\AppData\Local\Temp\claude\h--development-projects-AUDia-AUDiaGentic\7cc783d7-5e01-4bf2-9c53-db8095b37fa2\scratchpad\gp18_trace.log"


def _gp18_trace(message: str) -> None:
    import datetime
    import os

    try:
        with open(_GP18_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now(datetime.UTC).isoformat()} pid={os.getpid()} {message}\n")
    except OSError:
        pass


class CdpError(RuntimeError):
    """A CDP command returned an error."""


class CdpProtocolError(CdpError):
    """The CDP server itself rejected a command with a JSON-RPC "error"
    field -- a genuine protocol-level failure (e.g. "No target with given
    id found"), as opposed to a transport/connection failure (socket
    closed, client stopped, stale connection detected). Only this subtype
    is safe evidence that the command's target itself is gone; every other
    CdpError means the command's outcome is simply unknown."""


class CdpStaleGenerationError(CdpError):
    """A session-scoped command's required_generation no longer matches.

    GP18 review follow-up: closes the TOCTOU race where a caller fetches a
    sessionId (bound to connection generation N), then before the command
    carrying it is actually sent, a self-healing reconnect bumps the
    connection to generation N+1 -- sending the generation-N sessionId over
    generation-N+1's WebSocket fails with CDP error -32001 "Session with
    given id not found", exactly the failure GP18 was meant to eliminate.
    A caller passing required_generation gets this raised BEFORE send
    instead, so it can re-fetch a fresh session and retry once rather than
    silently sending a doomed request.
    """


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
        devtools_active_port_file: Path | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.default_timeout = default_timeout
        self.connect_timeout = connect_timeout or default_timeout
        self.devtools_active_port_file = devtools_active_port_file
        self._socket: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self.events: asyncio.Queue[CdpEvent] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        # GP18 review follow-up: serializes the stale-check + reconnect
        # sequence in _ensure_connected(). Without this, two concurrent
        # command() calls can both observe a dead reader task and both
        # reconnect, or one can observe self._socket briefly as None while
        # another task is mid-reconnect -- confirmed as a real gap in code
        # review, not yet reproduced live (this runtime does serve multiple
        # projects concurrently, so the interleaving is realistic).
        self._connect_lock = asyncio.Lock()
        self._stopping = False
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._owner_thread: int | None = None
        self._timed_out_ids: dict[int, float] = {}
        # GP18: bumped every time _ensure_connected() performs a genuine
        # (re)connect. CDP target-attachment sessionIds are scoped to the
        # specific WebSocket connection they were established on -- a
        # caller (e.g. PythonCdpBridge) that caches sessionIds must detect
        # a generation change and invalidate them, or every subsequent
        # Target.* call using a stale sessionId fails with CDP error
        # -32001 "Session with given id not found."
        self.connection_generation = 0

    async def start(self) -> None:
        await self._ensure_connected()

    async def _ensure_connected(self) -> None:
        """(Re)establish the connection, self-healing a stale one.

        GP18: a socket reference alone is not proof the async transport is
        still usable. The reader task that actually delivers command
        responses can die (e.g. its owning event loop was torn down
        between two independent callers of a machine-scoped singleton
        client) while the socket object and pending-futures map remain
        untouched -- confirmed live: a new command() registered a future
        that nothing was left alive to ever resolve, so it waited the full
        default_timeout and failed via wait_for's own timeout, not a
        prompt connection error. Called from both start() (first-ever
        connect) and the top of command() (every call, since start() is
        only invoked once per bridge lifetime by callers -- the actual
        hot path that needs self-healing goes through command(), not a
        repeated start() call).

        GP18 review follow-up: the entire check-then-reconnect sequence
        runs under _connect_lock so concurrent callers serialize on the
        connection decision rather than racing (one reconnecting while
        another observes a transient None/half-migrated state).
        """
        async with self._connect_lock:
            current_loop = asyncio.get_running_loop()
            if self._socket is not None:
                stale = (
                    self._reader_task is None
                    or self._reader_task.done()
                    or self._reader_task.get_loop() is not current_loop
                )
                if not stale:
                    return
                _gp18_trace(
                    f"_ensure_connected() detected STALE client (reader_done={self._reader_task.done() if self._reader_task else None}) "
                    f"-- forcing reconnect instead of reuse; current_loop={id(current_loop)} "
                    f"owner_loop={id(self._owner_loop) if self._owner_loop else None} pending={tuple(self._pending)}"
                )
                stale_error = CdpError("CDP reader task was found dead on reuse; connection was stale")
                for future in tuple(self._pending.values()):
                    if not future.done():
                        future.set_exception(stale_error)
                self._pending.clear()
                stale_socket, self._socket = self._socket, None
                stale_task, self._reader_task = self._reader_task, None
                if stale_task is not None and not stale_task.done():
                    stale_task.cancel()
                try:
                    await stale_socket.close()
                except Exception:  # noqa: BLE001 - best-effort cleanup of a dead connection
                    pass
            self._stopping = False
            websocket_url = await asyncio.to_thread(self._discover_websocket_url, self.connect_timeout)
            self._socket = await connect(
                websocket_url, max_size=None, open_timeout=self.connect_timeout
            )
            self._owner_loop = current_loop
            self._owner_thread = threading.get_ident()
            self._reader_task = asyncio.create_task(self._read_loop())
            self.connection_generation += 1
            _gp18_trace(
                f"_ensure_connected() fresh connect: owner_loop={id(current_loop)} owner_thread={threading.get_ident()} "
                f"reader_task_loop={id(self._reader_task.get_loop())} generation={self.connection_generation}"
            )

    def _discover_websocket_url(self, timeout: float | None = None) -> str:
        if self.endpoint.startswith(("ws://", "wss://")):
            return self.endpoint
        url = self.endpoint + "/json/version"
        try:
            with urllib.request.urlopen(url, timeout=timeout or self.default_timeout) as response:
                payload = json.load(response)
        except (OSError, ValueError):
            return self._discover_from_active_port_file()
        value = payload.get("webSocketDebuggerUrl")
        if not isinstance(value, str) or not value:
            raise CdpError("CDP /json/version did not provide webSocketDebuggerUrl")
        return value

    def _discover_from_active_port_file(self) -> str:
        path = self.devtools_active_port_file
        if path is None:
            raise CdpError("CDP discovery failed and no DevToolsActivePort file is configured")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            port = int(lines[0])
            socket_path = lines[1].strip()
        except (OSError, ValueError, IndexError) as exc:
            raise CdpError("DevToolsActivePort file is missing or malformed") from exc
        if not 1 <= port <= 65535 or not socket_path.startswith("/devtools/browser/"):
            raise CdpError("DevToolsActivePort file contains unsafe endpoint data")
        return f"ws://127.0.0.1:{port}{socket_path}"

    async def command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
        required_generation: int | None = None,
    ) -> Any:
        await self._ensure_connected()
        if required_generation is not None and required_generation != self.connection_generation:
            # GP18 review follow-up: _ensure_connected() just ran and may
            # have reconnected -- check BEFORE send, not after, so a stale
            # sessionId is never actually transmitted.
            raise CdpStaleGenerationError(
                f"stale connection generation for session-scoped command {method}: "
                f"required {required_generation}, current {self.connection_generation}"
            )
        socket = self._socket
        if socket is None:
            raise CdpError("CDP client is not connected")
        request_id = self._next_id
        self._next_id += 1
        current_loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = current_loop.create_future()
        self._pending[request_id] = future
        message: dict[str, Any] = {"id": request_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        t0 = time.monotonic()
        reader_loop = self._reader_task.get_loop() if self._reader_task else None
        _gp18_trace(
            f"cdp.command.begin id={request_id} method={method} current_loop={id(current_loop)} "
            f"owner_loop={id(self._owner_loop) if self._owner_loop else None} reader_loop={id(reader_loop) if reader_loop else None} "
            f"loops_match={current_loop is reader_loop} reader_done={self._reader_task.done() if self._reader_task else None} "
            f"pending={tuple(self._pending)}"
        )
        try:
            lock_t = time.monotonic()
            async with self._send_lock:
                _gp18_trace(f"cdp.send_lock.acquired id={request_id} waited={time.monotonic() - lock_t:.4f}")
                send_t = time.monotonic()
                await socket.send(json.dumps(message, separators=(",", ":")))
                _gp18_trace(f"cdp.send.returned id={request_id} duration={time.monotonic() - send_t:.4f}")
            wait_t = time.monotonic()
            try:
                result = await asyncio.wait_for(future, timeout or self.default_timeout)
                _gp18_trace(f"cdp.command.completed id={request_id} total={time.monotonic() - t0:.4f}")
                return result
            except TimeoutError:
                self._timed_out_ids[request_id] = time.monotonic()
                _gp18_trace(
                    f"cdp.command.timeout id={request_id} waited={time.monotonic() - wait_t:.4f} "
                    f"total={time.monotonic() - t0:.4f} pending={tuple(self._pending)}"
                )
                raise
        finally:
            self._pending.pop(request_id, None)

    async def _read_loop(self) -> None:
        socket = self._socket
        if socket is None:
            return
        failure: Exception | None = None
        try:
            async for raw in socket:
                _gp18_trace(f"cdp.raw.received len={len(raw)} loop={id(asyncio.get_running_loop())}")
                value = json.loads(raw)
                if "id" in value:
                    response_id = int(value["id"])
                    future = self._pending.get(response_id)
                    if response_id in self._timed_out_ids:
                        latency = time.monotonic() - self._timed_out_ids.pop(response_id)
                        _gp18_trace(f"LATE_CDP_RESPONSE id={response_id} latency={latency:.4f}")
                    _gp18_trace(
                        f"cdp.response.correlate id={response_id} pending_found={future is not None} "
                        f"future_done={future.done() if future else None} pending_ids={tuple(self._pending)}"
                    )
                    if future is None or future.done():
                        continue
                    if "error" in value:
                        error = value["error"]
                        future.set_exception(CdpProtocolError(str(error)))
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
