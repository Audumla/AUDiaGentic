"""Operator interaction module — live ask, durable store, and push-status.

Provides ask/answer semantics over two surfaces:
- MCP elicitation (async-native, per-request ctx)
- CLI backend (sync stdin/stdout, set at composition root)

FI06: async-native ask path, Literal choice schema, contextvar ctx wiring,
error taxonomy, and ResponseStatus semantics fix.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

try:
    import pydantic
    from pydantic import BaseModel
    _HAS_PYDANTIC = True
except ImportError:
    pydantic = None  # type: ignore[assignment]
    _HAS_PYDANTIC = False

try:
    from mcp.server.elicitation import (
        AcceptedElicitation,
        CancelledElicitation,
        DeclinedElicitation,
    )
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False

logger = logging.getLogger(__name__)
DEFAULT_TTL_SECONDS = 8 * 60 * 60


class ResponseStatus(Enum):
    ANSWERED = "answered"
    DECLINED = "declined"
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


# ── MCP context wiring (FI06/RV129) ────────────────────────────────────────

_mcp_ctx_var: contextvars.ContextVar[tuple[Any, asyncio.AbstractEventLoop] | None] = \
    contextvars.ContextVar("_mcp_ctx", default=None)


# ── MCP elicitation schema ─────────────────────────────────────────────────

def _build_elicit_schema(choices: tuple[str, ...] | None) -> type[BaseModel] | None:  # type: ignore[name-defined]
    """Build a pydantic model for ctx.elicit from the request choices.

    For enumerated choices, generates a Literal-typed 'value' field so the
    MCP client renders the valid options.  For freeform, plain str.
    """
    if not _HAS_PYDANTIC or pydantic is None:
        return None

    from typing import Literal
    if choices:
        literal_type = Literal[tuple(choices)]  # type: ignore[type-arg]
        return pydantic.create_model(
            "ElicitChoice",
            value=(literal_type, ...),  # type: ignore[misc]
        )
    else:

        class _FreeformSchema(BaseModel):  # type: ignore[misc]
            value: str = ""

        return _FreeformSchema


def _parse_elicit_result(result: Any, request: AskRequest) -> AskResponse:
    """Convert an MCP ElicitationResult into an AskResponse.

    Status expresses transport outcome only (answered/declined/timed_out);
    the selected option lives exclusively in .choice.
    """
    if result is None:
        return AskResponse(
            request_id=request.request_id,
            status=ResponseStatus.TIMED_OUT,
        )

    if isinstance(result, AcceptedElicitation):  # type: ignore[arg-type]
        choice = getattr(result.data, "value", None) or ""
        return AskResponse(
            request_id=request.request_id,
            status=ResponseStatus.ANSWERED,
            choice=str(choice) if choice else None,
        )

    if isinstance(result, (DeclinedElicitation, CancelledElicitation)):  # type: ignore[arg-type]
        return AskResponse(
            request_id=request.request_id,
            status=ResponseStatus.DECLINED,
            details={"elicit_action": result.action},
        )

    logger.debug("Unrecognized elicitation result, returning timeout")
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

                return AskResponse(
                    request_id=request.request_id,
                    status=ResponseStatus.ANSWERED,
                    choice=choice or None,
                )
            else:
                print(f"\n{request.title}")  # noqa: T201
                if request.description:
                    print(f"  {request.description}")  # noqa: T201
                raw = input("> ").strip()
                return AskResponse(
                    request_id=request.request_id,
                    status=ResponseStatus.ANSWERED if raw else ResponseStatus.DECLINED,
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


# ── Async ask (FI06) ───────────────────────────────────────────────────────

async def ask_async(
    title: str,
    description: str = "",
    choices: tuple[str, ...] | list[str] | None = None,
    default_choice: str | None = None,
    timeout_seconds: int = 30,
    *,
    ctx: Any = None,
) -> AskResponse:
    """Async-native ask — awaits ctx.elicit directly under a timeout.

    When ctx is provided, performs live MCP elicitation.  Falls back to
    TIMED_OUT when no eligible context is available (non-blocking).
    """
    effective_ctx = ctx or _mcp_ctx_var.get()
    if isinstance(effective_ctx, tuple):
        effective_ctx = effective_ctx[0]

    if not effective_ctx or not hasattr(effective_ctx, "elicit"):
        logger.debug("ask_async: no eligible ctx available, returning timeout")
        return AskResponse(status=ResponseStatus.TIMED_OUT)

    request = AskRequest(
        title=title,
        description=description,
        choices=tuple(choices) if choices else (),
        default_choice=default_choice,
        timeout_seconds=timeout_seconds,
    )

    schema = _build_elicit_schema(request.choices)
    if schema is None:
        return AskResponse(status=ResponseStatus.TIMED_OUT)

    message = f"{request.title}\n\n{request.description}".strip() or request.title

    try:
        result = await asyncio.wait_for(
            effective_ctx.elicit(message, schema),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.debug("MCP elicitation timed out", extra={"title": title})
        return AskResponse(request_id=request.request_id, status=ResponseStatus.TIMED_OUT)
    except Exception as exc:
        if _HAS_MCP:
            try:
                from mcp import McpError
                if isinstance(exc, McpError):
                    logger.warning("MCP elicitation protocol failure", exc_info=True)
                    return AskResponse(request_id=request.request_id, status=ResponseStatus.TIMED_OUT)
            except ImportError:
                pass
        logger.warning("MCP elicitation failed", exc_info=True)
        return AskResponse(request_id=request.request_id, status=ResponseStatus.TIMED_OUT)

    return _parse_elicit_result(result, request)


# ── Public API ─────────────────────────────────────────────────────────────

def ask(
    title: str,
    description: str = "",
    choices: tuple[str, ...] | list[str] | None = None,
    default_choice: str | None = None,
    timeout_seconds: int = 30,
    *,
    persist: bool = False,
    project_root: Path | None = None,
) -> AskResponse:
    """Ask the operator a question. Returns an AskResponse.

    Resolution order: explicit global backend > MCP contextvar (with
    run_coroutine_threadsafe for cross-thread calls) > TIMED_OUT fallback.
    """
    if _backend is not None and hasattr(_backend, "ask"):
        request = AskRequest(
            title=title,
            description=description,
            choices=tuple(choices) if choices else (),
            default_choice=default_choice,
            timeout_seconds=timeout_seconds,
        )
        try:
            return _backend.ask(request)
        except Exception:
            logger.debug("Backend ask failed", exc_info=True)

    ctx_pair = _mcp_ctx_var.get()
    if ctx_pair is not None:
        mcp_ctx, loop = ctx_pair
        try:
            current: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        # Worker thread (no loop here) or a different loop: submit to the MCP
        # loop and block this thread. Same loop: cannot block without deadlock —
        # fall through to timeout (async callers must use ask_async/ask_via_ctx).
        if current is not loop:
            coro = ask_async(
                title, description, choices, default_choice, timeout_seconds, ctx=mcp_ctx,
            )
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            try:
                # ask_async enforces timeout_seconds internally via wait_for;
                # the outer margin only guards against a wedged loop.
                return future.result(timeout=timeout_seconds + 5)
            except TimeoutError:
                future.cancel()
                logger.warning("Cross-thread ask() did not complete", extra={"title": title})
                return AskResponse(status=ResponseStatus.TIMED_OUT)

    logger.debug("ask() called with no backend or ctx — returning timeout", extra={"title": title})
    if persist and project_root is not None:
        request_id = globals()["request"](
            kind="ask",
            title=title,
            description=description,
            choices=tuple(choices) if choices else (),
            project_root=project_root,
            ttl_seconds=timeout_seconds or DEFAULT_TTL_SECONDS,
        )
        return AskResponse(
            request_id=request_id,
            status=ResponseStatus.TIMED_OUT,
            details={"request_id": request_id},
        )
    return AskResponse(status=ResponseStatus.TIMED_OUT)


def interactions_root(project_root: Path) -> Path:
    from audiagentic.foundation.paths.names import project_marker_path

    return project_marker_path(project_root) / "runtime" / "interactions"


def interaction_path(project_root: Path, request_id: str) -> Path:
    return interactions_root(project_root) / f"{request_id}.json"


def _validate_record(payload: dict[str, Any]) -> None:
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.contracts.schema_registry import validate_with_schema

    issues = validate_with_schema("interaction-request", payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-INTERACT-001",
            kind="interaction",
            message="interaction request failed validation",
            details={"issues": issues},
        )


def read_record(project_root: Path, request_id: str) -> dict[str, Any]:
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    path = interaction_path(project_root, request_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-INTERACT-001",
            kind="interaction",
            message="failed to read interaction request",
            details={"request-id": request_id, "error": str(exc)},
        ) from exc
    _validate_record(payload)
    return payload


def write_record(project_root: Path, payload: dict[str, Any]) -> None:
    from audiagentic.foundation.io import atomic_write_json

    _validate_record(payload)
    atomic_write_json(interaction_path(project_root, payload["request_id"]), payload)


def _is_expired(payload: dict[str, Any], now_ts: str) -> bool:
    if payload.get("state") != "pending":
        return False
    requested_at = str(payload.get("requested_at", ""))
    ttl_seconds = int(payload.get("ttl_seconds") or DEFAULT_TTL_SECONDS)
    requested = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    expires = requested + timedelta(seconds=ttl_seconds)
    now = datetime.fromisoformat(now_ts.replace("Z", "+00:00"))
    return expires <= now


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    from audiagentic.foundation.event import DeliveryMode, get_bus

    get_bus().publish(event_type, payload, mode=DeliveryMode.SYNC)


def request(
    kind: str,
    title: str,
    *,
    description: str = "",
    choices: tuple[str, ...] | list[str] | None = None,
    source_kind: str = "",
    source_id: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    project_root: Path,
    request_id: str | None = None,
) -> str:
    """Persist a pending interaction request and publish interaction.requested."""
    from audiagentic.foundation.time import now_iso_z

    payload = {
        "contract-version": "v1",
        "request_id": request_id or uuid.uuid4().hex[:12],
        "kind": kind,
        "title": title,
        "description": description,
        "choices": list(choices or []),
        "state": "pending",
        "answer": None,
        "source_kind": source_kind,
        "source_id": source_id,
        "requested_at": now_iso_z(),
        "answered_at": None,
        "ttl_seconds": ttl_seconds,
    }
    write_record(project_root, payload)
    _publish("interaction.requested", dict(payload))
    return payload["request_id"]


def respond(
    request_id: str,
    choice: str | None,
    *,
    details: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> None:
    """Submit a response to a pending live or persisted ask."""
    if project_root is not None:
        from audiagentic.foundation.time import now_iso_z

        payload = read_record(project_root, request_id)
        payload["state"] = "answered"
        payload["answer"] = {"choice": choice, "details": dict(details or {})}
        payload["answered_at"] = now_iso_z()
        write_record(project_root, payload)
        _publish("interaction.answered", dict(payload))
        return

    if _backend is not None and hasattr(_backend, "respond"):
        try:
            _backend.respond(request_id, choice, details=details or {})
        except Exception:
            logger.debug("Backend respond failed", exc_info=True)


def get_response(
    request_id: str,
    *,
    project_root: Path,
    now_ts: str | None = None,
) -> AskResponse | None:
    """Poll a persisted interaction request."""
    from audiagentic.foundation.time import now_iso_z

    payload = read_record(project_root, request_id)
    if _is_expired(payload, now_ts or now_iso_z()):
        payload["state"] = "expired"
        write_record(project_root, payload)
        return AskResponse(request_id=request_id, status=ResponseStatus.TIMED_OUT)
    if payload.get("state") == "pending":
        return None
    if payload.get("state") == "answered":
        answer = payload.get("answer") or {}
        return AskResponse(
            request_id=request_id,
            status=ResponseStatus.ANSWERED,
            choice=answer.get("choice"),
            details=dict(answer.get("details") or {}),
        )
    return AskResponse(request_id=request_id, status=ResponseStatus.TIMED_OUT)


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
            _publish("interaction.status", {
                "component": component,
                "level": level,
                "message": message,
                "details": msg.details,
            })
            return
        except Exception:
            logger.debug("Backend push_status failed, falling back to log", exc_info=True)

    log_method = getattr(logger, level, logger.info)
    log_method(f"[{component}] {message}", extra={"details": msg.details})
    _publish("interaction.status", {
        "component": component,
        "level": level,
        "message": message,
        "details": msg.details,
    })
