from __future__ import annotations

import asyncio
import json

import pytest

from audiagentic.components.providers.adapters.gpt_auto.cdp.client import CdpClient


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
