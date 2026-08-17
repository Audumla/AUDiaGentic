from __future__ import annotations

import asyncio
import json

import pytest

from audiagentic.components.providers.adapters.gpt_auto.cdp.client import (
    CdpClient,
    CdpError,
    CdpStaleGenerationError,
)


def test_devtools_active_port_fallback_is_local_and_validated(tmp_path):
    marker = tmp_path / "DevToolsActivePort"
    marker.write_text("9333\n/devtools/browser/browser-id\n", encoding="utf-8")
    client = CdpClient("http://127.0.0.1:9222", devtools_active_port_file=marker)

    assert client._discover_from_active_port_file() == (
        "ws://127.0.0.1:9333/devtools/browser/browser-id"
    )


def test_devtools_active_port_rejects_non_browser_socket(tmp_path):
    marker = tmp_path / "DevToolsActivePort"
    marker.write_text("9333\n/ws/untrusted\n", encoding="utf-8")
    client = CdpClient("http://127.0.0.1:9222", devtools_active_port_file=marker)

    with pytest.raises(CdpError, match="unsafe endpoint"):
        client._discover_from_active_port_file()


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
async def test_command_self_heals_when_reader_task_is_dead(monkeypatch):
    """GP18: a dead reader task (e.g. from a torn-down event loop reusing a
    machine-scoped singleton client across independent callers) must
    trigger a reconnect on the next command(), not a silent hang until the
    full default_timeout elapses. Live-confirmed mechanism: the socket
    reference and pending-futures map survive a dead reader task
    untouched, so a new command registers a future nothing is left alive
    to ever resolve."""
    client = CdpClient("ws://unused")
    dead_socket = _Socket()
    client._socket = dead_socket
    client._reader_task = asyncio.create_task(client._read_loop())
    await dead_socket.close()  # let the reader task actually finish
    await asyncio.sleep(0)
    assert client._reader_task.done()

    fresh_socket = _ScriptedSocket('{"id":$ID,"result":{"ok":true}}')

    async def fake_connect(url, **kwargs):
        return fresh_socket

    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.gpt_auto.cdp.client.connect", fake_connect
    )
    monkeypatch.setattr(client, "_discover_websocket_url", lambda timeout=None: "ws://fresh")

    result = await client.command("Test.echo", timeout=1)

    assert result == {"ok": True}
    assert client._socket is fresh_socket
    await client.stop()


@pytest.mark.asyncio
async def test_command_rejects_stale_required_generation_before_send():
    """GP18 code-review follow-up: a session-scoped caller that captured a
    sessionId under connection_generation N must never have its command
    actually transmitted once the connection has since moved to N+1 --
    that would send a sessionId the browser has already invalidated (CDP
    -32001), exactly the failure GP18 set out to eliminate. The check must
    reject BEFORE send, not merely surface the browser's own error after
    the fact."""
    client = CdpClient("ws://unused")
    socket = _ScriptedSocket('{"id":$ID,"result":{"ok":true}}')
    client._socket = socket
    client._reader_task = asyncio.create_task(client._read_loop())
    client.connection_generation = 3
    try:
        with pytest.raises(CdpStaleGenerationError):
            await client.command("Test.echo", session_id="stale-session", required_generation=2, timeout=1)
        # A matching generation must still succeed normally.
        result = await client.command(
            "Test.echo", session_id="current-session", required_generation=3, timeout=1
        )
        assert result == {"ok": True}
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_ensure_connected_serializes_concurrent_reconnect_attempts(monkeypatch):
    """GP18 code-review follow-up: two concurrent callers observing the
    same dead reader task must not both perform an independent reconnect
    (wasting a connection and risking one seeing a half-migrated state) --
    _connect_lock must serialize the decision so only one real reconnect
    happens and both callers converge on the same fresh connection."""
    client = CdpClient("ws://unused")
    dead_socket = _Socket()
    client._socket = dead_socket
    client._reader_task = asyncio.create_task(client._read_loop())
    await dead_socket.close()
    await asyncio.sleep(0)
    assert client._reader_task.done()

    connect_calls = 0
    fresh_socket = _Socket()

    async def fake_connect(url, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        await asyncio.sleep(0.01)  # widen the window a real race would need
        return fresh_socket

    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.gpt_auto.cdp.client.connect", fake_connect
    )
    monkeypatch.setattr(client, "_discover_websocket_url", lambda timeout=None: "ws://fresh")

    try:
        await asyncio.gather(client._ensure_connected(), client._ensure_connected())
    finally:
        await client.stop()

    assert connect_calls == 1, "both callers must converge on ONE real reconnect, not race into two"


@pytest.mark.asyncio
async def test_cdp_client_stop_is_idempotent_and_does_not_publish_disconnect():
    client = CdpClient("ws://unused")
    socket = _Socket()
    client._socket = socket
    client._reader_task = asyncio.create_task(client._read_loop())
    await client.stop()
    await client.stop()
    assert client.events.empty()
