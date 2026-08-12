"""Public interaction API — ask, push_status, request_interaction, respond, get_response."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from audiagentic.foundation.event import DeliveryMode, get_bus
from audiagentic.foundation.interaction.backend import current_backend
from audiagentic.foundation.interaction.mcp import ask_async
from audiagentic.foundation.interaction.models import (
    DEFAULT_TTL_SECONDS,
    AskRequest,
    AskResponse,
    PushStatusMessage,
    ResponseStatus,
)
from audiagentic.foundation.interaction.store import (
    _is_expired,
    read_record,
    write_record,
)
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    get_bus().publish(event_type, payload, mode=DeliveryMode.SYNC)


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
    backend = current_backend()
    if backend is not None and hasattr(backend, "ask"):
        ask_req = AskRequest(
            title=title,
            description=description,
            choices=tuple(choices) if choices else (),
            default_choice=default_choice,
            timeout_seconds=timeout_seconds,
        )
        try:
            return backend.ask(ask_req)
        except Exception:
            logger.debug("Backend ask failed", exc_info=True)

    from audiagentic.foundation.interaction.mcp import _mcp_ctx_var

    ctx_pair = _mcp_ctx_var.get()
    if ctx_pair is not None:
        mcp_ctx, loop = ctx_pair
        try:
            current: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        # Worker thread (no loop here) or a different loop: submit to the MCP
        # loop and block this thread. Same loop: cannot block without deadlock --
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
        request_id = request_interaction(
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


def request_interaction(
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
        payload = read_record(project_root, request_id)
        payload["state"] = "answered"
        payload["answer"] = {"choice": choice, "details": dict(details or {})}
        payload["answered_at"] = now_iso_z()
        write_record(project_root, payload)
        _publish("interaction.answered", dict(payload))
        return

    backend = current_backend()
    if backend is not None and hasattr(backend, "respond"):
        try:
            backend.respond(request_id, choice, details=details or {})
        except Exception:
            logger.debug("Backend respond failed", exc_info=True)


def get_response(
    request_id: str,
    *,
    project_root: Path,
    now_ts: str | None = None,
) -> AskResponse | None:
    """Poll a persisted interaction request."""
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

    backend = current_backend()
    if backend is not None and hasattr(backend, "push_status"):
        try:
            backend.push_status(msg)
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
