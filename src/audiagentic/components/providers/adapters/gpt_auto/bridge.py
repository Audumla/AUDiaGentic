"""Concurrent provider-wide JSON-line bridge to Puppeteer."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import GptAutoConfig


@dataclass(frozen=True)
class BridgeEvent:
    name: str
    page_handle: str | None = None


class PuppeteerBridge:
    def __init__(self, config: GptAutoConfig) -> None:
        self.config = config
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self.events: asyncio.Queue[BridgeEvent] = asyncio.Queue()

    async def start(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node executable is required for gpt-auto")
        helper = Path(__file__).with_name("puppeteer_bridge.cjs")
        from .install import node_module_path

        env = os.environ.copy()
        managed_node_path = str(node_module_path())
        existing_node_path = env.get("NODE_PATH")
        env["NODE_PATH"] = managed_node_path + (
            os.pathsep + existing_node_path if existing_node_path else ""
        )
        self._proc = await asyncio.create_subprocess_exec(
            node,
            str(helper),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        params: dict[str, Any] = {
            "browserURL": self.config.cdp_url,
            "protocolTimeoutMs": int(self.config.cdp.protocol_timeout_seconds * 1000),
        }
        endpoint = self._devtools_ws_endpoint()
        if endpoint:
            params["browserWSEndpoint"] = endpoint
        try:
            await self.call("connect", params, timeout=self.config.cdp.connect_timeout_seconds)
        except Exception:
            await self.stop()
            raise

    def _devtools_ws_endpoint(self) -> str | None:
        path = self.config.cdp.devtools_active_port_file
        if path is None:
            path = (
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "BraveSoftware/Brave-Browser/User Data/DevToolsActivePort"
            )
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        if (
            len(lines) < 2
            or lines[0] != str(self.config.browser.remote_debugging_port)
            or not lines[1].startswith("/devtools/browser/")
        ):
            return None
        return f"ws://127.0.0.1:{lines[0]}{lines[1]}"

    async def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        proc = self._proc
        if not proc or not proc.stdin or proc.returncode is not None:
            raise RuntimeError("Puppeteer bridge is not running")
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = (
            json.dumps(
                {"id": request_id, "method": method, "params": params or {}}, separators=(",", ":")
            )
            + "\n"
        )
        try:
            async with self._write_lock:
                proc.stdin.write(message.encode("utf-8"))
                await proc.stdin.drain()
            return await asyncio.wait_for(
                future, timeout or self.config.cdp.protocol_timeout_seconds
            )
        finally:
            self._pending.pop(request_id, None)

    async def _read_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            while line := await self._proc.stdout.readline():
                value = json.loads(line)
                if "id" in value:
                    future = self._pending.get(int(value["id"]))
                    if future and not future.done():
                        if "error" in value:
                            future.set_exception(RuntimeError(value["error"]))
                        else:
                            future.set_result(value.get("result"))
                elif "event" in value:
                    await self.events.put(BridgeEvent(str(value["event"]), value.get("pageHandle")))
        finally:
            error = RuntimeError("Puppeteer bridge disconnected")
            for future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(error)
            await self.events.put(BridgeEvent("helper_disconnected"))

    async def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        while await self._proc.stderr.readline():
            pass

    async def stop(self) -> None:
        proc = self._proc
        if proc and proc.returncode is None:
            try:
                await self.call("disconnect", timeout=2)
            except Exception:
                pass
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        self._proc = None
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        self._reader_task = self._stderr_task = None
