"""Configuration-bound work-queue backend selection (SH25)."""

from __future__ import annotations

import os

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .backend import AgentWorkQueue, InMemoryAgentWorkQueue


def create_work_queue() -> AgentWorkQueue:
    """Create the configured backend without provider-specific branching.

    The in-memory backend is the only selectable implementation until a
    broker adapter passes the conformance suite. Unknown values fail closed;
    there is no silent fallback that could hide a misconfigured cutover.
    """
    backend = os.environ.get("AUDIAGENTIC_GATEWAY_QUEUE_BACKEND", "in-memory").strip().lower()
    if backend == "in-memory":
        return InMemoryAgentWorkQueue()
    raise AudiaGenticError(
        "CFG-AGW-110",
        "agents",
        "configured gateway queue backend is unavailable",
        {"backend": backend},
    )


__all__ = ["create_work_queue"]
