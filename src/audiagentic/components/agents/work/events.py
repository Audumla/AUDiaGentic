"""Best-effort Work milestone events (SH60).

Published after a durable mutation has completed and its lock has been released, never inside a lock. An event
is an observation, not a receipt: a crash after the commit may omit it, so reconciliation never depends on one.
Payloads carry only ids and a short digest of the delivery key: no principal, message text or inputs.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from audiagentic.components.agents.gateway import event_topics as topics

logger = logging.getLogger(__name__)

_KEY_DIGEST_CHARS = 12


def publish_work_event(topic: str, work: Mapping[str, Any], *, delivery_key: str | None = None,
                       execution_id: str | None = None) -> None:
    """Publish one Work milestone; never raises (a failing subscriber must not break Work)."""
    payload: dict[str, Any] = {"work-id": work["work_id"], "context-id": work["context_id"], "state": work["state"]}
    if delivery_key:
        payload["delivery-key"] = delivery_key[:_KEY_DIGEST_CHARS]
    if execution_id:
        payload["execution-id"] = execution_id
    try:
        from audiagentic.foundation.event import get_bus

        get_bus().publish(topic, payload)
    except Exception:  # noqa: BLE001 - observation only
        logger.warning("work event publish failed", extra={"topic": topic}, exc_info=True)


__all__ = ["publish_work_event", "topics"]
