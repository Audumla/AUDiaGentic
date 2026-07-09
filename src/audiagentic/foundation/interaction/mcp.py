"""MCP elicitation support for interaction."""
from __future__ import annotations

import asyncio
import contextvars
import logging
from typing import Any

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

from audiagentic.foundation.interaction.models import AskRequest, AskResponse, ResponseStatus

logger = logging.getLogger(__name__)


_mcp_ctx_var: contextvars.ContextVar[tuple[Any, asyncio.AbstractEventLoop] | None] = \
    contextvars.ContextVar("_mcp_ctx", default=None)


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
