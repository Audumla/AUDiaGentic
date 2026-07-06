from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

try:
    from mcp.server.elicitation import (
        AcceptedElicitation,
        CancelledElicitation,
        DeclinedElicitation,
    )
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False

try:
    from pydantic import BaseModel
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False

logger = logging.getLogger(__name__)


class ResponseStatus(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


@dataclass
class AskRequest:
    """A request sent to the user/operator for a decision."""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    choices: tuple[str, ...] = ()
    default_choice: str | None = None
    timeout_seconds: int = 30


@dataclass
class AskResponse:
    """Response to an ask request."""
    request_id: str = ""
    status: ResponseStatus = ResponseStatus.TIMED_OUT
    choice: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PushStatusMessage:
    """A one-way status update pushed to the operator."""
    component: str = ""
    level: str = "info"  # info, warning, error
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ── Backend abstraction ────────────────────────────────────────────────────

class InteractionBackend(Protocol):
    """Different surfaces (CLI input, MCP elicitation) implement this."""

    def ask(self, request: AskRequest) -> AskResponse: ...
    def push_status(self, msg: PushStatusMessage) -> None: ...
    def respond(self, request_id: str, choice: str | None, *, details: dict[str, Any]) -> None: ...


# ── MCP elicitation backend (FI02) ─────────────────────────────────────────

class McpAskBackend:
    """Wraps MCP ctx.elicit as the live-ask fast path.

    Uses a pydantic schema generated from the request choices to elicit
    a structured response from the connected MCP client.  Handles accept,
    decline, and cancel as real answers (not transport failures).
    """

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    def ask(self, request: AskRequest) -> AskResponse:
        if not _HAS_MCP or not hasattr(self._ctx, "elicit"):
            return AskResponse(status=ResponseStatus.TIMED_OUT)

        schema = _build_elicit_schema(request.choices)
        if schema is None:
            return AskResponse(status=ResponseStatus.TIMED_OUT)

        message = f"{request.title}\n\n{request.description}".strip() or request.title
        result = _elicit_sync(self._ctx, message, schema, timeout=request.timeout_seconds)
        return _parse_elicit_result(result, request)


def _build_elicit_schema(choices: tuple[str, ...] | None) -> type[BaseModel] | None:  # type: ignore[name-defined]
    """Build a pydantic model for ctx.elicit from the request choices."""
    if not _HAS_PYDANTIC:
        return None

    allowed = set(choices) if choices else None

    if allowed:

        class _ChoiceSchema(BaseModel):  # type: ignore[misc]
            value: str

            def __init__(self, **data: Any) -> None:
                super().__init__(**data)
                if self.value not in allowed:
                    from pydantic import ValidationError
                    raise ValidationError(_ChoiceSchema, f"value {self.value!r} not in {allowed}")

        return _ChoiceSchema
    else:

        class _FreeformSchema(BaseModel):  # type: ignore[misc]
            value: str = ""

        return _FreeformSchema


def _elicit_sync(ctx: Any, message: str, schema: type[Any], timeout: int) -> Any:
    """Run ctx.elicit synchronously by blocking on the current event loop."""
    coro = ctx.elicit(message, schema)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop().run_until_complete(coro)

    future = asyncio.ensure_future(coro, loop=loop)
    try:
        return loop.run_until_complete(asyncio.wait_for(future, timeout))
    except (asyncio.TimeoutError, Exception):
        if not future.done():
            future.cancel()
        return None


def _parse_elicit_result(result: Any, request: AskRequest) -> AskResponse:
    """Convert an MCP ElicitationResult into an AskResponse."""
    if result is None:
        return AskResponse(
            request_id=request.request_id,
            status=ResponseStatus.TIMED_OUT,
        )

    if isinstance(result, AcceptedElicitation):  # type: ignore[arg-type]
        choice = getattr(result.data, "value", None) or ""
        return AskResponse(
            request_id=request.request_id,
            status=ResponseStatus.APPROVED,
            choice=str(choice) if choice else None,
        )

    if isinstance(result, (DeclinedElicitation, CancelledElicitation)):  # type: ignore[arg-type]
        return AskResponse(
            request_id=request.request_id,
            status=ResponseStatus.REJECTED,
            details={"elicit_action": result.action},
        )

    logger.debug("Unrecognized elicitation result, returning timeout", exc_info=True)
    return AskResponse(status=ResponseStatus.TIMED_OUT)


# ── CLI backend (FI04) ─────────────────────────────────────────────────────

class CliBackend:
    """Sync backend that uses sys.stdin/sys.stdout for interaction."""

    def ask(self, request: AskRequest) -> AskResponse:
        try:
            if request.choices:
                print(f"\n{request.title}")  # noqa: T201
                if request.description:
                    print(f"  {request.description}")  # noqa: T201
                for i, c in enumerate(request.choices, 1):
                    print(f"  [{i}] {c}")  # noqa: T201
                default = request.default_choice
                if default:
                    idx = list(request.choices).index(default) + 1
                    print(f"  (default: [{idx}] {default})")  # noqa: T201
                else:
                    idx = 1
                    default = request.choices[0] if request.choices else ""
                    print(f"  (default: [{idx}] {default})")  # noqa: T201

                raw = input("> ").strip()
                if not raw:
                    choice = default
                else:
                    try:
                        sel = int(raw) - 1
                        choice = request.choices[sel] if 0 <= sel < len(request.choices) else default
                    except ValueError:
                        choice = raw if raw in request.choices else default

                status = ResponseStatus.APPROVED if choice != "rejected" else ResponseStatus.REJECTED
                return AskResponse(
                    request_id=request.request_id,
                    status=status,
                    choice=choice or None,
                )
            else:
                print(f"\n{request.title}")  # noqa: T201
                if request.description:
                    print(f"  {request.description}")  # noqa: T201
                raw = input("> ").strip()
                return AskResponse(
                    request_id=request.request_id,
                    status=ResponseStatus.APPROVED if raw else ResponseStatus.REJECTED,
                    choice=raw or None,
                )
        except (EOFError, KeyboardInterrupt):
            return AskResponse(status=ResponseStatus.TIMED_OUT)
        except Exception:
            logger.debug("CLI ask failed", exc_info=True)
            return AskResponse(status=ResponseStatus.TIMED_OUT)

    def push_status(self, msg: PushStatusMessage) -> None:
        prefix = f"[{msg.component}] " if msg.component else ""
        print(f"{prefix}{msg.message}")  # noqa: T201

    def respond(self, request_id: str, choice: str | None, *, details: dict[str, Any]) -> None:
        pass


# ── Global backend ─────────────────────────────────────────────────────────

_backend: InteractionBackend | None = None


def set_backend(backend: InteractionBackend) -> None:
    """Set the live interaction backend. Call once at harness startup."""
    global _backend
    _backend = backend


def clear_backend() -> None:
    """Clear the backend. Useful for test teardown."""
    global _backend
    _backend = None


# ── Public API ─────────────────────────────────────────────────────────────

def ask(
    title: str,
    description: str = "",
    choices: tuple[str, ...] | list[str] | None = None,
    default_choice: str | None = None,
    timeout_seconds: int = 30,
) -> AskResponse:
    """Ask the operator a question. Returns an AskResponse.

    If no backend is configured, returns a timed-out response (non-blocking).
    The caller should handle TIMED_OUT gracefully.
    """
    if _backend is None:
        logger.debug(
            "ask() called with no backend configured — returning timeout",
            extra={"title": title},
        )
        return AskResponse(status=ResponseStatus.TIMED_OUT)

    request = AskRequest(
        title=title,
        description=description,
        choices=tuple(choices) if choices else (),
        default_choice=default_choice,
        timeout_seconds=timeout_seconds,
    )
    return _backend.ask(request)


def get_response(
    ask_id: str,
    *,
    choices: tuple[str, ...] | None = None,
    default_choice: str | None = None,
) -> AskResponse:
    """Get a named response. Convenience wrapper around ask() for
    well-known decisions (e.g. job approval, reload confirmation).

    Uses the ask_id as the title if no explicit title is provided.
    """
    return ask(
        title=ask_id,
        choices=choices or (),
        default_choice=default_choice,
    )


def push_status(
    component: str,
    message: str,
    *,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> None:
    """Push a one-way status update to the operator surface.

    This is a fire-and-forget notification — does not block or expect a response.
    When no backend is configured, logs at the given level.
    """
    msg = PushStatusMessage(
        component=component,
        level=level,
        message=message,
        details=dict(details) if details else {},
    )

    if _backend is not None and hasattr(_backend, "push_status"):
        try:
            _backend.push_status(msg)
            return
        except Exception:
            logger.debug("Backend push_status failed, falling back to log", exc_info=True)

    log_method = getattr(logger, level, logger.info)
    log_method(f"[{component}] {message}", extra={"details": msg.details})


def respond(
    request_id: str,
    choice: str | None,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    """Submit a response to a pending ask. Intended for test harnesses and
    async backends that decouple the ask from the answer."""
    if _backend is not None and hasattr(_backend, "respond"):
        try:
            _backend.respond(request_id, choice, details=details or {})
        except Exception:
            logger.debug("Backend respond failed", exc_info=True)
