"""Canonical event ingress adapter for the trigger migration."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import AgentWorkRecord
from .ingress import submit_event_work
from .triggers import trigger_matches


def dispatch_trigger_event(
    project_root: Path,
    *,
    trigger: Mapping[str, Any],
    event_type: str,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    context_id: str,
    prompt: str,
) -> AgentWorkRecord | None:
    """Evaluate one trigger and submit one replay-safe Work when matched."""
    if not trigger_matches(
        trigger,
        event_type=event_type,
        payload=payload,
        metadata=metadata,
    ):
        return None
    delivery_id = str(
        (metadata or {}).get("event-id")
        or (metadata or {}).get("delivery-id")
        or f"{event_type}:{(metadata or {}).get('correlation-id', '')}"
    )
    return submit_event_work(
        project_root,
        context_id=context_id,
        source=str(trigger.get("trigger-id", "event-trigger")),
        delivery_id=delivery_id,
        text=prompt,
        inputs={"event-type": event_type, "payload": dict(payload)},
    )
