"""MCP server base for component API servers.

Provides the FastMCP factory (name resolved from component config),
async output bridging so component MCP servers can stream progress and
log events without coupling to the transport layer, and the
log_tool_call decorator for automatic tool call tracing.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import queue
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

from audiagentic.foundation.contracts.output import (
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


def log_tool_call(func: Callable) -> Callable:
    """Decorator that adds entry/exit/error logging to an MCP tool function.

    Stacking order — @mcp.tool() must be outermost, @log_tool_call innermost:

        @mcp.tool()
        @log_tool_call
        def my_tool(...): ...

    Logs tool name + correlation ID at DEBUG on entry; duration_ms at INFO on
    success; full traceback at ERROR on failure. Args are never logged —
    they may contain secrets, API keys, or user PII (security invariant).
    """
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.debug(
                "tool call start",
                extra={"tool": func.__name__},
            )
            t0 = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                logger.info(
                    "tool call done",
                    extra={
                        "tool": func.__name__,
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                    },
                )
                return result
            except Exception:
                logger.error(
                    "tool call failed",
                    extra={"tool": func.__name__},
                    exc_info=True,
                )
                raise
        return _async_wrapper

    @functools.wraps(func)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.debug(
            "tool call start",
            extra={"tool": func.__name__},
        )
        t0 = time.monotonic()
        try:
            result = func(*args, **kwargs)
            logger.info(
                "tool call done",
                extra={
                    "tool": func.__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return result
        except Exception:
            logger.error(
                "tool call failed",
                extra={"tool": func.__name__},
                exc_info=True,
            )
            raise
    return _sync_wrapper


def project_root_from_env() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if repo_root:
        return Path(repo_root)
    raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")


def _resolve_mcp_server_name(module_name: str) -> str:
    """Return the MCP server name declared for module_name in component config YAMLs."""
    try:
        from audiagentic.foundation.components.loader import register_all_components
        from audiagentic.foundation.components.registry import all_descriptors
        register_all_components()
        for descriptor in all_descriptors().values():
            for server in descriptor.mcp_servers:
                if server.module == module_name:
                    return server.name
    except Exception:
        logger.warning("Failed to resolve MCP server name for %s", module_name, exc_info=True)
    return module_name


def mcp_server(module_name: str, instructions: str = "") -> FastMCP:
    """Create a FastMCP instance whose name is resolved from component config."""
    name = _resolve_mcp_server_name(module_name)
    return FastMCP(name, instructions=instructions)


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
        elif progress < self._next_progress:
            progress = self._next_progress
        self._next_progress = progress + 1.0
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
    """Run a sync component API call in a worker thread, bridging output to MCP."""
    if ctx is None:
        return work(None)

    events: queue.Queue[ComponentOutputEvent] = queue.Queue()
    bridge = McpOutputBridge(ctx, logger=logger)

    def sink(event: ComponentOutputEvent) -> None:
        events.put(coerce_output_event(event))

    task = asyncio.create_task(asyncio.to_thread(work, sink))
    last_emit = asyncio.get_running_loop().time()

    while not task.done():
        emitted = False
        while True:
            try:
                await bridge.emit(events.get_nowait())
                emitted = True
            except queue.Empty:
                break
        if emitted:
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
