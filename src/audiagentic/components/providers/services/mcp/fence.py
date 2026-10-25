"""One reentrant actor fence for cooperating native MCP ownership writers."""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from audiagentic.foundation.system.advisory_lock import AdvisoryLock

from .managed_mcp_registry import mcp_ownership_registry

_held = ContextVar("native_mcp_fences", default=frozenset())


@contextmanager
def native_mcp_fence(root):
    path = mcp_ownership_registry(root).path.with_suffix(".lock").resolve()
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    identity = (str(path), threading.get_ident(), id(task))
    if identity in _held.get():
        yield
        return
    with AdvisoryLock(path):
        token = _held.set(_held.get() | {identity})
        try:
            yield
        finally:
            _held.reset(token)
