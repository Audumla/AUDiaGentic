"""Codex app-server native client and join adapter declaration (SH54).

The Codex app-server speaks JSON-RPC 2.0 over WebSocket framing; ``codex app-server --listen
unix://PATH`` serves any number of independent clients on one socket. This module is the one place
that knows that protocol: it connects, correlates responses by id, buffers notifications and applies
bounded timeouts. ``JOIN_ADAPTER`` declares the adapter identity qualification evidence is bound to
(``join_readiness.adapter_identity`` digests this file), so a change here invalidates old evidence.

Nothing here creates sessions on its own or kills anything: callers own the processes they start.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.session.join_readiness import JoinAdapterInfo

#: The Codex app-server protocol generation this adapter speaks (``codex app-server generate-json-schema``).
NATIVE_SCHEMA_VERSION = "app-server-v2"

JOIN_ADAPTER = JoinAdapterInfo(adapter_id="codex-app-server", adapter_version="1",
                               native_schema_version=NATIVE_SCHEMA_VERSION)

#: Methods this adapter relies on; an installed Codex missing any of them is not this protocol.
REQUIRED_METHODS = frozenset({
    "initialize", "thread/start", "thread/list", "thread/loaded/list", "thread/read",
    "thread/resume", "thread/unsubscribe",
})


class AppServerError(RuntimeError):
    """A JSON-RPC error answer, a closed connection or a timeout; never carries payloads."""

    def __init__(self, kind: str, method: str, code: int | None = None) -> None:
        super().__init__(f"{kind}: {method}" + (f" ({code})" if code is not None else ""))
        self.kind, self.method, self.code = kind, method, code


class AppServerClient:
    """One independent client connection to a running app-server socket."""

    def __init__(self, socket_path: Path, name: str, *, timeout: float = 15.0) -> None:
        self.name = name
        self._path = Path(socket_path)
        self._timeout = timeout
        self._ws: Any = None
        self._next = 0
        self.notifications: deque[dict[str, Any]] = deque(maxlen=200)

    async def connect(self) -> AppServerClient:
        from websockets.asyncio.client import unix_connect

        self._ws = await asyncio.wait_for(unix_connect(str(self._path), "ws://localhost/"), self._timeout)
        return self

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise AppServerError("not-connected", method)
        self._next += 1
        ident = self._next
        await self._ws.send(json.dumps({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}}))
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppServerError("timeout", method)
            try:
                raw = await asyncio.wait_for(self._ws.recv(), remaining)
            except TimeoutError:
                raise AppServerError("timeout", method) from None
            except Exception as error:  # noqa: BLE001 - a closed socket is a protocol-level fact, not a crash
                raise AppServerError("closed", method) from error
            message = json.loads(raw)
            if message.get("id") == ident and "method" not in message:
                if "error" in message:
                    raise AppServerError("rpc-error", method, (message["error"] or {}).get("code"))
                return message.get("result") or {}
            self.notifications.append(message)

    async def wait_for(self, method: str, timeout: float, *, match: Any = None) -> dict[str, Any] | None:
        """The next notification named ``method`` (already seen, or arriving within ``timeout``), else None.

        ``match`` may filter on the notification's params. Responses to requests are not consumed here.
        """
        deadline = time.monotonic() + timeout
        seen = 0
        while True:
            pending = list(self.notifications)
            for message in pending[seen:]:
                if message.get("method") == method and (match is None or match(message.get("params") or {})):
                    return message
            seen = len(pending)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self._ws is None:
                return None
            try:
                raw = await asyncio.wait_for(self._ws.recv(), remaining)
            except TimeoutError:
                return None
            except Exception:  # noqa: BLE001 - a closed socket ends the wait
                return None
            message = json.loads(raw)
            if "method" in message:
                self.notifications.append(message)
                if len(self.notifications) == self.notifications.maxlen:
                    seen = max(0, seen - 1)

    async def initialize(self) -> dict[str, Any]:
        result = await self.request("initialize", {
            "clientInfo": {"name": f"audiagentic-qualify-{self.name}", "version": "1"}, "capabilities": {}})
        await self._ws.send(json.dumps({"jsonrpc": "2.0", "method": "initialized"}))
        return result

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            finally:
                self._ws = None


class OwnedAppServer:
    """An app-server process this caller started on a Unix socket, stopped by its exact process group."""

    def __init__(self, executable: Path, socket_path: Path, env: dict[str, str], cwd: Path) -> None:
        self._argv = [str(executable), "app-server", "--listen", f"unix://{socket_path}"]
        self._env, self._cwd, self.socket_path = env, cwd, socket_path
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, timeout: float = 20.0) -> OwnedAppServer:
        self.process = subprocess.Popen(  # noqa: S603 - fixed argv, scrubbed environment
            self._argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=self._env, cwd=self._cwd, start_new_session=True)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.socket_path.exists():
                return self
            if self.process.poll() is not None:
                raise AppServerError("exited", "start", self.process.returncode)
            time.sleep(0.1)
        self.stop()
        raise AppServerError("timeout", "start")

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> bool:
        """Terminate the owned process group; True when it is gone."""
        if self.process is None:
            return True
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
        return self.process.poll() is not None
