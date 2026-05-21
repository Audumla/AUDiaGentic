"""Shared MCP server helpers.

Component APIs own behavior. MCP servers should only translate project root,
tool arguments, structured component output, and final return values.
"""

from __future__ import annotations

import asyncio
import os
import queue
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from audiagentic.foundation.output import (
    ComponentOutputEvent,
    ComponentOutputSink,
    coerce_output_event,
)

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import Context
except ImportError:  # pragma: no cover
    FastMCP = Any  # type: ignore[misc, assignment]
    Context = Any  # type: ignore[misc, assignment]

T = TypeVar("T")


def project_root_from_env() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if repo_root:
        return Path(repo_root)
    raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")


def mcp_server(component_name: str, instructions: str) -> FastMCP:
    return FastMCP(component_name, instructions=instructions)


class McpOutputBridge:
    """Translate component output events into MCP progress/log notifications."""

    def __init__(self, ctx: Context | None, *, logger: str | None = None) -> None:
        self._ctx = ctx
        self._logger = logger
        self._next_progress = 1.0

    async def emit(self, event: str | ComponentOutputEvent) -> None:
        if self._ctx is None:
            return
        output = coerce_output_event(event)
        logger_name = output.logger or self._logger
        if output.kind == "log":
            await self._ctx.log(output.level, output.message, logger_name=logger_name)
            return
        progress = output.progress
        if progress is None:
            progress = self._next_progress
            self._next_progress += 1.0
        else:
            self._next_progress = max(self._next_progress, progress + 1.0)
        await self._ctx.report_progress(progress, total=output.total, message=output.message)


async def run_blocking_with_output(
    *,
    ctx: Context | None,
    logger: str,
    work: Callable[[ComponentOutputSink | None], T],
    heartbeat_message: str | None = None,
    heartbeat_seconds: float = 10.0,
    poll_seconds: float = 0.25,
) -> T:
    """Run sync component API in a worker thread and bridge output to MCP."""
    if ctx is None:
        return work(None)

    events: queue.Queue[ComponentOutputEvent] = queue.Queue()
    bridge = McpOutputBridge(ctx, logger=logger)

    def sink(event: ComponentOutputEvent) -> None:
        events.put(coerce_output_event(event))

    task = asyncio.create_task(asyncio.to_thread(work, sink))
    last_emit = asyncio.get_running_loop().time()

    while not task.done():
        latest: ComponentOutputEvent | None = None
        while True:
            try:
                latest = events.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            await bridge.emit(latest)
            last_emit = asyncio.get_running_loop().time()
        elif heartbeat_message and asyncio.get_running_loop().time() - last_emit >= heartbeat_seconds:
            await bridge.emit(ComponentOutputEvent(message=heartbeat_message))
            last_emit = asyncio.get_running_loop().time()
        await asyncio.sleep(poll_seconds)

    result = await task
    while True:
        try:
            await bridge.emit(events.get_nowait())
        except queue.Empty:
            break
    return result
