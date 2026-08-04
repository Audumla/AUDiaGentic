"""Explicit test-only isolation for the in-process gateway queue."""
from __future__ import annotations


def reset_gateway_queue() -> None:
    """Install a fresh queue manager for a test-owned gateway scenario.

    The production gateway still owns one manager per hosting process. Tests
    need an explicit boundary because multiple scenarios reuse the default
    profile id while using different temporary project roots.
    """
    from audiagentic.components.agents.gateway import api as agents_gateway_api
    from audiagentic.components.agents.gateway.queue import queue as agents_gateway_queue

    agents_gateway_api.set_queue_manager(agents_gateway_queue.GatewayQueueManager())
