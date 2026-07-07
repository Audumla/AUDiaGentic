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
import queue
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from audiagentic.foundation.contracts.errors import AudiaGenticError, to_error_envelope
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
logger = logging.getLogger(__name__)

_SENSITIVE_DETAIL_KEYS = {
    "stdout",
    "stderr",
    "output",
    "prompt",
    "input",
    "token",
    "secret",
    "password",
    "authorization",
    "api-key",
    "api_key",
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)(=|:)\s*([^\s,;]+)"),
)


def _redact_string(value: str, *, limit: int = 500) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1\2 [redacted]", redacted)
    if len(redacted) > limit:
        return f"{redacted[:limit]}...[truncated]"
    return redacted


def _redact_error_value(key: str, value: Any) -> Any:
    key_l = key.lower()
    if any(token in key_l for token in _SENSITIVE_DETAIL_KEYS):
        return "[redacted]"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {str(k): _redact_error_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_error_value(key, item) for item in value]
    return value


def _redact_error_envelope(error: AudiaGenticError) -> dict[str, Any]:
    envelope = to_error_envelope(error)
    details = envelope.get("details")
    if isinstance(details, dict):
        envelope["details"] = {
            str(key): _redact_error_value(str(key), value)
            for key, value in details.items()
        }
    return envelope


def server_instructions(decl: Any) -> str:
    """Return MCP server instructions from a server declaration, or empty string."""
    if decl is None:
        return ""
    return getattr(decl, "instructions", "") or ""


def tool_description(decl: Any, name: str) -> str:
    """Return tool description from a server declaration, or empty string."""
    if decl is None:
        return ""
    descriptions = getattr(decl, "tool_descriptions", None)
    if not descriptions:
        return ""
    return descriptions.get(name, "")


def report_error(
    label: str, tool_name: str, exc: Exception, logger: logging.Logger
) -> dict[str, Any]:
    """Return a standardized MCP error envelope, logging the failure."""
    logger.exception("%s tool failed: %s", label, tool_name)
    if isinstance(exc, AudiaGenticError):
        envelope = _redact_error_envelope(exc)
        envelope["tool"] = tool_name
        return envelope
    return {"ok": False, "error": _redact_string(str(exc)), "tool": tool_name}


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
    """Resolve the project root being operated on.

    Honors an explicit AUDIAGENTIC_REPO_ROOT override (needed when the package
    is installed somewhere other than the target project); otherwise derives it
    generically by walking up from CWD — the MCP server runs with CWD set to the
    project root, so no path needs to be hard-coded anywhere.
    """
    from audiagentic.paths import find_project_root

    root = find_project_root()
    if root is None:
        raise AudiaGenticError(
            code="CFG-MCP-001",
            kind="mcp",
            message="could not locate project root",
            details={
                "hint": (
                    "AUDIAGENTIC_REPO_ROOT is not set and no .audiagentic/ "
                    "marker was found walking up from CWD"
                )
            },
        )
    return root


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


class _AutoDescFastMCP(FastMCP):  # type: ignore[misc,valid-type]
    """FastMCP subclass that auto-injects YAML tool descriptions.

    When a tool is registered via ``@mcp.tool()`` without an explicit
    description, this class resolves the module → server declaration lookup
    and pulls the description from ``tool_descriptions`` in config.
    Falls back to *none* (not the docstring) when no YAML description exists.
    """

    def __init__(self, module_name: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._module_name = module_name
        # Cache resolved declaration to avoid repeated registry lookups.
        self._decl: Any = None

    def _get_decl(self) -> Any:
        if self._decl is None:
            try:
                from audiagentic.foundation.components.loader import register_all_components
                from audiagentic.foundation.components.registry import all_descriptors

                register_all_components()
                server_name = _resolve_mcp_server_name(self._module_name)
                if server_name is None:
                    self._decl = None
                    return None
                for descriptor in all_descriptors().values():
                    for srv in descriptor.mcp_servers:
                        if srv.name == server_name:
                            self._decl = srv
                            return srv
            except Exception:
                logger.warning(
                    "Failed to resolve tool-description decl for %s",
                    self._module_name,
                    exc_info=True,
                )
            self._decl = None
        return self._decl

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Any], Any]:
        # Detect when @mcp.tool() is used without a description argument.
        has_desc = False
        if args and isinstance(args[0], str):
            has_desc = True  # positional description arg
        elif "description" in kwargs:
            has_desc = True

        if not has_desc:
            decl = self._get_decl()
            if decl is not None:
                # Return a custom decorator that resolves the function name at decoration time.
                def _custom_decorator(func: Any) -> Any:
                    desc = tool_description(decl, func.__name__)
                    if desc:
                        kwargs["description"] = desc
                    return super(_AutoDescFastMCP, self).tool(*args, **kwargs)(func)  # type: ignore[misc]

                return _custom_decorator  # type: ignore[return-value]

        return super().tool(*args, **kwargs)


def mcp_server(module_name: str, instructions: str = "") -> FastMCP:
    """Create a FastMCP instance whose name is resolved from component config.

    Tools registered via ``@mcp.tool()`` (no explicit description) automatically
    pick up their description from the server's ``tool-descriptions`` YAML block.
    """
    name = _resolve_mcp_server_name(module_name)
    return _AutoDescFastMCP(module_name, name, instructions=instructions)  # type: ignore[return-value]


def run_mcp_server(server: FastMCP, bootstrap_name: str) -> None:
    """Bootstrap logging and run an MCP server over stdio.

    Shared entry-point body so component MCP servers do not each re-implement
    the bootstrap + run sequence.
    """
    from audiagentic.foundation.logging import bootstrap
    bootstrap(bootstrap_name)
    server.run()


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
    """Run a sync component API call in a worker thread, bridging output to MCP.

    Also sets the interaction contextvar so sync ask() calls can reach live
    MCP elicitation via run_coroutine_threadsafe (FI06/RV129).
    """
    if ctx is None:
        return work(None)

    from audiagentic.foundation import interaction as _interaction_mod

    _ctx_token = _interaction_mod._mcp_ctx_var.set((ctx, asyncio.get_running_loop()))
    try:
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
    finally:
        _interaction_mod._mcp_ctx_var.reset(_ctx_token)


async def ask_via_ctx(
    ctx: Context,
    title: str,
    description: str = "",
    choices: tuple[str, ...] | list[str] | None = None,
    default_choice: str | None = None,
    timeout_seconds: int = 30,
) -> Any:
    """Sanctioned entry point for MCP tool handlers to perform live elicitation.

    Mirrors the McpOutputBridge pattern: per-request ctx, not global backend.
    """
    from audiagentic.foundation.interaction import ask_async
    return await ask_async(title, description, choices, default_choice, timeout_seconds, ctx=ctx)
