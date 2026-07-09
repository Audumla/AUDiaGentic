from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from audiagentic.foundation import interaction
from audiagentic.foundation.interaction import (
    AskRequest,
    AskResponse,
    ResponseStatus,
)


@dataclass
class _Backend:
    response: AskResponse
    seen: AskRequest | None = None

    def ask(self, request: AskRequest) -> AskResponse:
        self.seen = request
        return self.response

    def push_status(self, msg) -> None:
        pass

    def respond(self, request_id: str, choice: str | None, *, details: dict) -> None:
        pass


class _Ctx:
    def __init__(self, result=None) -> None:
        self.result = result
        self.called = threading.Event()
        self.messages: list[str] = []

    async def elicit(self, message: str, schema):
        self.messages.append(message)
        self.called.set()
        return self.result


def teardown_function() -> None:
    from audiagentic.foundation.interaction.mcp import _mcp_ctx_var

    interaction.clear_backend()
    _mcp_ctx_var.set(None)


def test_ask_returns_timeout_without_backend_or_ctx() -> None:
    response = interaction.ask("Reload?")

    assert response.status is ResponseStatus.TIMED_OUT


def test_ask_uses_configured_sync_backend() -> None:
    backend = _Backend(AskResponse(status=ResponseStatus.ANSWERED, choice="yes"))
    interaction.set_backend(backend)

    response = interaction.ask("Reload?", choices=("yes", "no"))

    assert response.status is ResponseStatus.ANSWERED
    assert response.choice == "yes"
    assert backend.seen is not None
    assert backend.seen.choices == ("yes", "no")


def test_ask_async_without_ctx_times_out() -> None:
    async def _run() -> AskResponse:
        return await interaction.ask_async("Reload?")

    response = asyncio.run(_run())

    assert response.status is ResponseStatus.TIMED_OUT


def test_sync_ask_on_same_loop_does_not_block_or_elicit() -> None:
    async def _run() -> tuple[AskResponse, _Ctx]:
        loop = asyncio.get_running_loop()
        ctx = _Ctx()
        from audiagentic.foundation.interaction.mcp import _mcp_ctx_var

        token = _mcp_ctx_var.set((ctx, loop))
        try:
            return interaction.ask("Reload?", timeout_seconds=1), ctx
        finally:
            _mcp_ctx_var.reset(token)

    response, ctx = asyncio.run(_run())

    assert response.status is ResponseStatus.TIMED_OUT
    assert not ctx.called.is_set()


def test_sync_ask_from_worker_thread_submits_to_mcp_loop() -> None:
    ready = threading.Event()
    stop = threading.Event()
    ctx = _Ctx()
    box: dict[str, object] = {}

    def _loop_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        box["loop"] = loop
        ready.set()
        loop.run_until_complete(asyncio.to_thread(stop.wait))
        loop.close()

    thread = threading.Thread(target=_loop_thread)
    thread.start()
    assert ready.wait(timeout=5)
    loop = box["loop"]
    from audiagentic.foundation.interaction.mcp import _mcp_ctx_var

    token = _mcp_ctx_var.set((ctx, loop))
    try:
        response = interaction.ask("Reload?", timeout_seconds=1)
    finally:
        _mcp_ctx_var.reset(token)
        stop.set()
        thread.join(timeout=5)

    assert ctx.called.is_set()
    assert response.status is ResponseStatus.TIMED_OUT
    assert ctx.messages == ["Reload?"]
