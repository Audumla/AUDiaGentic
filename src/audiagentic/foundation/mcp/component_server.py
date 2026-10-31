"""MCP server base for component API servers.

Provides the FastMCP factory (name resolved from component config),
async output bridging so component MCP servers can stream progress and
log events without coupling to the transport layer, and the
tool_boundary decorator for tool call tracing and error redaction.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.contracts.output import (
    ComponentOutputEvent,
    ComponentOutputSink,
    coerce_output_event,
)
from audiagentic.foundation.logging.redaction import (
    DEFAULT_REDACT_PATTERNS,
    redact_error_envelope,
    redact_text,
)

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp.server.fastmcp.server import Context
    from mcp.types import CallToolResult
except ImportError:  # pragma: no cover
    FastMCP = Any  # type: ignore[misc, assignment]
    Context = Any  # type: ignore[misc, assignment]
    ToolError = RuntimeError  # type: ignore[misc, assignment]
    CallToolResult = Any  # type: ignore[misc, assignment]

T = TypeVar("T")
logger = logging.getLogger(__name__)

# Redaction primitives moved to foundation/logging/redaction.py — single
# source of truth for sensitive-key matching and pattern-based redaction.
# Local variants are forbidden by §15 (Output Redaction).


def server_instructions(decl: Any) -> str:
    """Return MCP server instructions from a server declaration, or empty string."""
    if decl is None:
        return ""
    return getattr(decl, "instructions", "") or ""


def tool_description(decl: Any, name: str) -> str:
    """Return tool description from a server declaration, or empty string.

    Handles both plain-string and rich-format (dict with 'description' key) specs.
    """
    if decl is None:
        return ""
    descriptions = getattr(decl, "tool_descriptions", None)
    if not descriptions:
        return ""
    entry = descriptions.get(name, "")
    if isinstance(entry, dict):
        return entry.get("description", "")
    return entry


def tool_parameter_spec(decl: Any, name: str) -> dict[str, Any]:
    """Return parameter description mapping from a rich-format tool spec, or empty dict.

    Rich format in YAML:
      tool-descriptions:
        some_tool:
          description: "..."
          parameters:
            param_name: "description for this parameter"

    Returns {param_name: {"description": "...", ...}} suitable for JSON Schema injection.
    """
    if decl is None:
        return {}
    descriptions = getattr(decl, "tool_descriptions", None)
    if not descriptions:
        return {}
    entry = descriptions.get(name, "")
    if not isinstance(entry, dict):
        return {}
    raw_params = entry.get("parameters", {})
    if not raw_params:
        return {}
    schema: dict[str, Any] = {}
    for param_name, param_desc in raw_params.items():
        if isinstance(param_desc, str):
            schema[param_name] = {"description": param_desc}
        elif isinstance(param_desc, dict):
            schema[param_name] = param_desc
    return schema


def _tool_error_text(exc: Exception, tool_name: str, log: logging.Logger) -> str:
    """Redact an exception into client-safe ToolError text.

    Operators get the full structured envelope in the log record; callers get
    code + redacted message + resolution. Fail-closed: if secret-shaped
    content survives redaction, the text collapses to a generic failure.
    """
    if isinstance(exc, AudiaGenticError):
        envelope = redact_error_envelope(exc)
        log.error("tool failed", extra={"tool": tool_name, "error": envelope})
        parts = [f"{envelope['error-code']}: {redact_text(envelope['message'])}"]
        resolution = envelope.get("resolution")
        if resolution:
            parts.append(f"resolution: {resolution}")
        details = envelope.get("details") or {}
        if details:
            parts.append(f"details: {json.dumps(details, sort_keys=True)}")
        text = "\n".join(parts)
    else:
        text = redact_text(str(exc))
        log.error("tool failed", extra={"tool": tool_name}, exc_info=True)

    # Fail-closed: if any secret-shaped content survives, collapse to a
    # generic error rather than leaking partial secrets. The key-value
    # pattern (api_key/token/secret/password) is already handled by
    # redact_text, which replaces the value with [REDACTED], so skip it here.
    for pattern in DEFAULT_REDACT_PATTERNS:
        if pattern.pattern.startswith(r"(https?://"):
            continue  # URL-credential patterns have special replacement
        if r"api[_-]?key|token|secret|password" in pattern.pattern:
            continue  # key-value pattern already redacted by redact_text
        if pattern.search(text):
            return "tool failed"
    return text


def tool_boundary(func: Callable) -> Callable:
    """Adapter boundary for an MCP tool: trace the call, redact and translate errors.

    Stacking order — @mcp.tool() must be outermost, @tool_boundary innermost:

        @mcp.tool()
        @tool_boundary
        def my_tool(...): ...

    Logs tool name at DEBUG on entry and duration_ms at INFO on success. On
    failure, raises ToolError with redacted, client-safe text and logs the
    full structured envelope at ERROR for operators. Args are never logged —
    they may contain secrets, API keys, or user PII (security invariant).

    Tools return domain data or raise. A tool must never return an
    error-shaped dict: the declared return type describes every value the
    tool can produce, which is what makes its outputSchema honest.
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
            except Exception as exc:
                raise ToolError(_tool_error_text(exc, func.__name__, logger)) from exc
            logger.info(
                "tool call done",
                extra={
                    "tool": func.__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return result

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
        except Exception as exc:
            raise ToolError(_tool_error_text(exc, func.__name__, logger)) from exc
        logger.info(
            "tool call done",
            extra={
                "tool": func.__name__,
                "duration_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        return result

    return _sync_wrapper


def project_root_from_env() -> Path:
    """Resolve the project root being operated on.

    Honors an explicit AUDIAGENTIC_REPO_ROOT override (needed when the package
    is installed somewhere other than the target project); otherwise derives it
    generically by walking up from CWD — the MCP server runs with CWD set to the
    project root, so no path needs to be hard-coded anywhere.
    """
    from audiagentic.foundation.mcp.worktree import current_worktree
    from audiagentic.foundation.paths.project import find_project_root

    selected = current_worktree()
    if selected is not None:
        return selected.path
    root = find_project_root()
    if root is None:
        raise make_error(
            prefix="CFG",
            component="MCP",
            number=1,
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

    def __init__(
        self,
        module_name: str,
        *args: Any,
        structured_output_only: bool = False,
        structured_output_tool_names: frozenset[str] = frozenset(),
        **kwargs: Any,
    ) -> None:
        self._module_name = module_name
        # Cache resolved declaration to avoid repeated registry lookups.
        self._decl: Any = None
        if not kwargs.get("instructions"):
            # The YAML ``instructions`` reach clients for every server, not
            # only those that thread them through by hand.
            kwargs["instructions"] = server_instructions(self._get_decl())
        super().__init__(*args, **kwargs)
        self._structured_output_only = structured_output_only
        self._structured_output_tool_names = frozenset(structured_output_tool_names)

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

    def _worktree_scoped(self) -> bool:
        return bool(getattr(self._get_decl(), "worktree_scoped", False))

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

    def add_tool(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        """Register SDK-derived schemas with optional transport-only metadata."""
        name = kwargs.get("name") or (args[0] if args else None) or fn.__name__
        selected = self._structured_output_only or name in self._structured_output_tool_names
        if self._worktree_scoped():
            fn = _worktree_scoped_wrapper(fn, name, structured=selected)
        if selected:
            fn = _structured_output_only_wrapper(fn)
        super().add_tool(fn, *args, **kwargs)

        # MCP SDK 1.27.0 exposes the registered Tool through get_tool().
        tool = self._tool_manager.get_tool(name)
        if tool is None:
            raise ValueError(f"registered MCP tool not found: {name}")
        try:
            _apply_parameter_descriptions(tool, tool_parameter_spec(self._get_decl(), name))
            if self._worktree_scoped():
                from audiagentic.foundation.mcp.worktree import WORKTREE_PARAMETER

                # Explained once in the server instructions, not on every tool.
                tool.parameters["properties"][WORKTREE_PARAMETER] = {"type": "string"}
            if selected:
                _align_structured_output_schema(tool)
                if self._worktree_scoped():
                    _declare_worktree_output(tool)
            _slim_tool_schemas(tool)
        except (TypeError, ValueError):
            self._tool_manager.remove_tool(name)
            raise


def _worktree_scoped_wrapper(fn: Any, name: str, *, structured: bool = False) -> Any:
    """Add the shared ``worktree`` argument and report the worktree each call used.

    The worktree is resolved and confirmed before the tool runs and is visible
    to it only through ``project_root_from_env()``. Mapping results gain a
    ``worktree`` key; any other result becomes ``{"result": value, "worktree": ...}``.
    On a structured-output server the worktree sits beside ``result`` in the
    one structured envelope (``{"result": value, "worktree": ...}``).
    """
    from audiagentic.foundation.mcp.worktree import (
        WORKTREE_PARAMETER,
        resolve_worktree,
        using_worktree,
    )

    signature = inspect.signature(fn, eval_str=True)
    if WORKTREE_PARAMETER in signature.parameters:
        raise ValueError(f"MCP tool {name}: {WORKTREE_PARAMETER!r} is reserved for worktree selection")
    if inspect.iscoroutinefunction(fn):
        raise ValueError(f"MCP tool {name}: worktree-scoped tools must be synchronous")

    def _report(value: Any, worktree: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            if WORKTREE_PARAMETER in value:
                raise ValueError(f"MCP tool {name} returned a reserved {WORKTREE_PARAMETER!r} key")
            return {**value, WORKTREE_PARAMETER: worktree.to_dict()}
        return {"result": value, WORKTREE_PARAMETER: worktree.to_dict()}

    def _scoped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        requested = kwargs.pop(WORKTREE_PARAMETER, None)
        try:
            worktree = resolve_worktree(requested)
        except Exception as exc:
            raise ToolError(_tool_error_text(exc, name, logger)) from exc
        with using_worktree(worktree):
            value = fn(*args, **kwargs)
        if structured:
            return CallToolResult(
                content=[], structuredContent={"result": value, WORKTREE_PARAMETER: worktree.to_dict()}
            )
        return _report(value, worktree)

    _scoped.__name__ = getattr(fn, "__name__", name)
    _scoped.__qualname__ = getattr(fn, "__qualname__", name)
    _scoped.__doc__ = fn.__doc__
    _scoped.__module__ = fn.__module__
    parameters = [*signature.parameters.values()]
    parameters.append(
        inspect.Parameter(WORKTREE_PARAMETER, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=str | None)
    )
    # A structured server keeps the tool's own result type for its schema; the
    # worktree is declared beside it by _declare_worktree_output.
    returns = signature.return_annotation if structured else dict[str, Any]
    _scoped.__signature__ = signature.replace(parameters=parameters, return_annotation=returns)  # type: ignore[attr-defined]
    _scoped.__annotations__ = {
        **{parameter.name: parameter.annotation for parameter in parameters},
        "return": returns,
    }
    return _scoped


def _declare_worktree_output(tool: Any) -> None:
    """Declare the reported worktree in a structured tool's output schema."""
    schema = tool.fn_metadata.output_schema
    if not schema:
        return
    schema.setdefault("properties", {})["worktree"] = {
        "type": "object",
        "description": "The git worktree this call acted on.",
        "properties": {
            "path": {"type": "string"},
            "branch": {"type": ["string", "null"]},
            "head": {"type": ["string", "null"]},
        },
        "required": ["path", "branch", "head"],
    }
    tool.__dict__.pop("output_schema", None)


_NAME_KEYED = frozenset({"properties", "patternProperties", "$defs", "definitions"})
_LITERAL = frozenset({"enum", "const", "default", "examples", "required"})


def _without_null_branch(node: dict[str, Any]) -> dict[str, Any]:
    """Publish an optional ``X | None`` as ``X``: omitting the argument is the null case."""
    branches = node.get("anyOf")
    if not isinstance(branches, list) or len(branches) != 2:
        return node
    kept = [branch for branch in branches if branch != {"type": "null"}]
    if len(kept) != 1 or not isinstance(kept[0], dict):
        return node
    return {**{key: value for key, value in node.items() if key != "anyOf"}, **kept[0]}


def _slim_schema(node: Any, *, names: bool = False) -> Any:
    """Drop generated ``title`` keys and ``default: null`` from schema objects.

    ``names`` marks a map keyed by property/definition names, whose keys are
    kept and whose values are schemas. Literal-valued keywords are copied as is.
    """
    if isinstance(node, list):
        return [_slim_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    if names:
        return {key: _slim_schema(value) for key, value in node.items()}
    node = _without_null_branch(node)
    slim: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        if key == "default" and value is None:
            continue
        slim[key] = value if key in _LITERAL else _slim_schema(value, names=key in _NAME_KEYED)
    return slim


def _slim_tool_schemas(tool: Any) -> None:
    """Token diet for the schemas sent to clients: input and output carry no generated titles."""
    tool.parameters = _slim_schema(tool.parameters)
    schema = tool.fn_metadata.output_schema
    if schema:
        tool.fn_metadata.output_schema = _slim_schema(schema)
    tool.__dict__.pop("output_schema", None)


def _apply_parameter_descriptions(tool: Any, descriptions: dict[str, Any]) -> None:
    """Overlay YAML prose only on SDK-generated input properties."""
    properties = tool.parameters.get("properties", {})
    unknown = set(descriptions) - set(properties)
    if unknown:
        raise ValueError(f"MCP tool {tool.name}: unknown parameter descriptions: {sorted(unknown)}")
    for name, annotation in descriptions.items():
        if (
            not isinstance(annotation, dict)
            or set(annotation) != {"description"}
            or not isinstance(annotation["description"], str)
        ):
            raise ValueError(
                f"MCP tool {tool.name}: parameter {name!r} must declare only a description"
            )
        properties[name]["description"] = annotation["description"]


def _align_structured_output_schema(tool: Any) -> None:
    """Describe the existing structured-only {"result": value} wire envelope."""
    metadata = tool.fn_metadata
    if metadata.output_model is None:
        # Explicit CallToolResult / untyped tools retain their SDK contract.
        return

    from pydantic import create_model

    # SDK 1.27.0 resolves annotations at registration. Primitive/list
    # returns already have a result field; mappings use an unwrapped model.
    result_type = (
        metadata.output_model.model_fields["result"].annotation
        if metadata.wrap_output
        else metadata.output_model
    )
    result_model = create_model(f"{tool.name}StructuredResult", result=(result_type, ...))
    metadata.output_model = result_model
    metadata.output_schema = result_model.model_json_schema()
    metadata.wrap_output = False
    tool.__dict__.pop("output_schema", None)


def _structured_output_only_wrapper(fn: Any) -> Any:
    """Make a typed FastMCP tool return structuredContent without text shadow data."""
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def _async(*args: Any, **kwargs: Any) -> Any:
            return _as_structured_only(await fn(*args, **kwargs))

        return _async

    @functools.wraps(fn)
    def _sync(*args: Any, **kwargs: Any) -> Any:
        return _as_structured_only(fn(*args, **kwargs))

    return _sync


def _as_structured_only(value: Any) -> Any:
    if isinstance(value, CallToolResult):
        return value
    return CallToolResult(content=[], structuredContent={"result": value})


def mcp_server(
    module_name: str,
    instructions: str = "",
    *,
    structured_output_only: bool = False,
    structured_output_tool_names: frozenset[str] = frozenset(),
) -> FastMCP:
    """Create a FastMCP instance whose name is resolved from component config.

    A server declared ``worktree-scoped: true`` gives every tool the shared
    per-call ``worktree`` argument (``foundation.mcp.worktree``): one session
    can act on any of its git worktrees, and each result reports the worktree
    used.

    Tools registered via ``@mcp.tool()`` (no explicit description) automatically
    pick up their description from the server's ``tool-descriptions`` YAML block.
    """
    name = _resolve_mcp_server_name(module_name)
    return _AutoDescFastMCP(
        module_name,
        name,
        instructions=instructions,
        structured_output_only=structured_output_only,
        structured_output_tool_names=structured_output_tool_names,
    )  # type: ignore[return-value]


_IDLE_TIMEOUT_SECONDS = 12 * 60 * 60.0
_WATCHDOG_POLL_SECONDS = 60.0


class _RequestActivityTracker:
    """Timestamp of the most recent genuine MCP request, not wall-clock-since-launch.

    ``clock`` is injectable so tests can drive idle-timeout logic without
    waiting 12 real hours.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last_activity = clock()

    def mark(self) -> None:
        with self._lock:
            self._last_activity = self._clock()

    def idle_seconds(self) -> float:
        with self._lock:
            return self._clock() - self._last_activity


def _tracking_wrapper(
    handler: Callable[..., Any], tracker: _RequestActivityTracker
) -> Callable[..., Any]:
    @functools.wraps(handler)
    async def _tracked(*args: Any, **kwargs: Any) -> Any:
        tracker.mark()
        return await handler(*args, **kwargs)

    return _tracked


def _install_activity_tracking(server: FastMCP) -> _RequestActivityTracker:
    """Wrap every registered MCP request handler so idleness reflects real traffic.

    FastMCP exposes no dedicated per-request hook; the lowlevel ``Server`` it
    wraps keeps every request type's handler (tools/list, tools/call,
    resources/*, prompts/*, ...) in a plain dict, ``request_handlers``,
    populated as the component registers tools. Wrapping each entry here
    marks activity on any genuine incoming request, without reimplementing
    stdio framing or touching sys.stdin directly.
    """
    tracker = _RequestActivityTracker()
    mcp_server = server._mcp_server  # type: ignore[attr-defined]
    for request_type, handler in list(mcp_server.request_handlers.items()):
        mcp_server.request_handlers[request_type] = _tracking_wrapper(handler, tracker)
    return tracker


@dataclass(frozen=True)
class _ParentLiveness:
    """Captured identity of the process to watch for liveness."""

    pid: int
    creation_identity: str | None


def _capture_parent_liveness(pid: int | None = None) -> _ParentLiveness:
    """Snapshot the parent's (or an explicit pid's) OS creation-time identity.

    Reuses the creation-identity primitive from managed_process.py rather than
    a PID-reuse-vulnerable "is this PID number still running" check: PIDs are
    recycled by the OS, so a bare pid_alive() check can false-positive on an
    unrelated process that happens to land on the same number later.
    """
    from audiagentic.foundation.system.managed_process import process_creation_identity

    target_pid = pid if pid is not None else os.getppid()
    return _ParentLiveness(pid=target_pid, creation_identity=process_creation_identity(target_pid))


def _parent_is_live(parent: _ParentLiveness) -> bool:
    """True while the originally-captured parent process still holds that pid.

    If no creation-identity fingerprint could be captured at startup
    (platform or permission gap), falls back to a plain liveness check --
    a documented, conservative limitation: it cannot detect PID reuse in
    that case, but it also never fires on a live, unrelated process when the
    fingerprint *was* captured.
    """
    from audiagentic.foundation.system.managed_process import process_creation_identity
    from audiagentic.foundation.system.process import pid_alive

    if not pid_alive(parent.pid):
        return False
    if parent.creation_identity is None:
        return True
    return process_creation_identity(parent.pid) == parent.creation_identity


def _watchdog_tick(
    tracker: _RequestActivityTracker,
    parent: _ParentLiveness,
    *,
    idle_timeout_seconds: float,
) -> str | None:
    """Return the self-termination reason if one applies now, else None."""
    if not _parent_is_live(parent):
        return "parent-exited"
    if tracker.idle_seconds() >= idle_timeout_seconds:
        return "idle-timeout"
    return None


def _start_self_termination_watchdog(
    server: FastMCP,
    *,
    idle_timeout_seconds: float = _IDLE_TIMEOUT_SECONDS,
    poll_seconds: float = _WATCHDOG_POLL_SECONDS,
    exit_fn: Callable[[int], None] = os._exit,
) -> tuple[threading.Thread, _RequestActivityTracker]:
    """Start the background watchdog thread; return it plus its activity tracker.

    Two independent, scoped safeguards against orphaned stdio MCP server
    processes (root cause: ``server.run()`` only returns on stdin EOF, which
    the OS does not reliably deliver to an orphaned child, especially on
    Windows): parent-liveness (an identity check, not a PID-reuse-prone
    liveness check) and a 12h idle timeout measured by genuine request
    traffic. Runs as a daemon thread so it never blocks the blocking
    ``server.run()`` call owned by FastMCP; fires ``os._exit(0)`` on either
    condition -- this is a disposable, host-respawned subprocess, so no
    graceful-shutdown ceremony is warranted.
    """
    tracker = _install_activity_tracking(server)
    parent = _capture_parent_liveness()

    def _poll() -> None:
        while True:
            time.sleep(poll_seconds)
            reason = _watchdog_tick(tracker, parent, idle_timeout_seconds=idle_timeout_seconds)
            if reason is not None:
                logger.warning(
                    "mcp server self-terminating",
                    extra={"reason": reason, "parent_pid": parent.pid},
                )
                exit_fn(0)
                return

    thread = threading.Thread(target=_poll, name="mcp-self-termination-watchdog", daemon=True)
    thread.start()
    return thread, tracker


def run_mcp_server(server: FastMCP, bootstrap_name: str) -> None:
    """Bootstrap logging and run an MCP server over stdio.

    Shared entry-point body so component MCP servers do not each re-implement
    the bootstrap + run sequence. Also starts the self-termination watchdog
    (parent-liveness + 12h idle timeout) so an orphaned copy of this process
    does not outlive the session that spawned it.
    """
    from audiagentic.foundation.logging import bootstrap

    bootstrap(bootstrap_name)
    _start_self_termination_watchdog(server)
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
            elif (
                heartbeat_message
                and asyncio.get_running_loop().time() - last_emit >= heartbeat_seconds
            ):
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
