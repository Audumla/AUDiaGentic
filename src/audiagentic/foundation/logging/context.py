"""Correlation ID propagation via contextvars.

A single correlation ID is generated per harness session (or per MCP server
process). It flows automatically into every JSON log line via the JSON
formatter in logging/config.py.

Works correctly across asyncio tasks (contextvars are copied into child tasks
by default) and thread pools (call new_correlation_id() in the worker thread
if you want a distinct ID, or inherit the parent context if you want the same).
"""
from __future__ import annotations

import contextvars
import uuid

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audiagentic_correlation_id", default=None
)


def new_correlation_id() -> str:
    """Generate a fresh UUID4 correlation ID, store it, and return it."""
    cid = uuid.uuid4().hex[:16]
    _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> contextvars.Token[str | None]:
    """Set an explicit correlation ID (e.g. from an inbound request header)."""
    return _correlation_id.set(cid)


def get_correlation_id() -> str | None:
    """Return the current correlation ID or None if not set."""
    return _correlation_id.get()


def reset_correlation_id(token: contextvars.Token[str | None] | None = None) -> None:
    """Reset correlation ID.

    With a token: restore the previous value (from set_correlation_id).
    Without a token: clear to None (used by reset_logging_for_test).
    """
    if token is None:
        _correlation_id.set(None)
    else:
        _correlation_id.reset(token)
