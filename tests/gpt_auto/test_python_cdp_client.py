from __future__ import annotations

import asyncio
import json

import pytest

from audiagentic.components.providers.adapters.gpt_auto.cdp.client import CdpClient, CdpError


class _Socket:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.messages.get()
        if value is None:
            raise StopAsyncIteration
        return value

    async def send(self, raw: str) -> None:
        request = json.loads(raw)
        await asyncio.sleep((20 - int(request["id"])) / 10_000)
        await self.messages.put(
            json.dumps({"id": request["id"], "result": {"echo": request["params"]}})
        )

    async def close(self) -> None:
        self.closed = True
        await self.messages.put(None)


@pytest.mark.asyncio
async def test_cdp_client_correlates_concurrent_out_of_order_commands():
    client = CdpClient("ws://unused")
    socket = _Socket()
    client._socket = socket
    client._reader_task = asyncio.create_task(client._read_loop())
    try:
        values = await asyncio.gather(
            *(client.command("Test.echo", {"value": value}) for value in range(20))
        )
        assert [value["echo"]["value"] for value in values] == list(range(20))
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_cdp_client_publishes_disconnect_when_socket_closes_cleanly():
    client = CdpClient("ws://unused")
    socket = _Socket()
    client._socket = socket
    client._reader_task = asyncio.create_task(client._read_loop())
    await socket.messages.put(None)
    event = await asyncio.wait_for(client.events.get(), timeout=1)
    assert event.method == "cdp.disconnected"
    await client.stop()


class _ScriptedSocket(_Socket):
    def __init__(self, response: str | None = None, *, delay: float = 0) -> None:
        super().__init__()
        self.response = response
        self.delay = delay

    async def send(self, raw: str) -> None:
        request = json.loads(raw)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.response is not None:
            await self.messages.put(self.response.replace("$ID", str(request["id"])))


@pytest.mark.asyncio
async def test_cdp_client_surfaces_protocol_errors_and_cleans_pending():
    client = CdpClient("ws://unused")
    socket = _ScriptedSocket('{"id":$ID,"error":{"code":-32601,"message":"missing"}}')
    client._socket = socket
    client._reader_task = asyncio.create_task(client._read_loop())
    try:
        with pytest.raises(CdpError, match="missing"):
            await client.command("Missing.method")
        assert client._pending == {}
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_cdp_client_command_timeout_removes_pending_and_late_reply_is_ignored():
    client = CdpClient("ws://unused")
    socket = _ScriptedSocket()
    client._socket = socket
    client._reader_task = asyncio.create_task(client._read_loop())
    try:
        with pytest.raises(TimeoutError):
            await client.command("Slow.method", timeout=0.01)
        assert client._pending == {}
        await socket.messages.put('{"id":1,"result":{"late":true}}')
        await asyncio.sleep(0.01)
        assert client._pending == {}
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_cdp_client_stop_is_idempotent_and_does_not_publish_disconnect():
    client = CdpClient("ws://unused")
    socket = _Socket()
    client._socket = socket
    client._reader_task = asyncio.create_task(client._read_loop())
    await client.stop()
    await client.stop()
    assert client.events.empty()
