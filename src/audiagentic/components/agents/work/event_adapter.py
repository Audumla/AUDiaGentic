"""Canonical event ingress adapter for the trigger migration."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import AgentWorkRecord
from .ingress import deterministic_work_id
from .service import get_work
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
    supplied_delivery_id = (metadata or {}).get("event-id") or (metadata or {}).get("delivery-id")
    if supplied_delivery_id:
        delivery_id = str(supplied_delivery_id)
    else:
        # Event-bus publishers are not required to provide a delivery id.
        # Derive one from the immutable event contents so replay still maps
        # to the same Work/Gateway admission key.
        canonical = json.dumps(
            {
                "event-type": event_type,
                "payload": payload,
                "metadata": metadata or {},
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        delivery_id = f"derived:{hashlib.sha256(canonical.encode()).hexdigest()}"
    from audiagentic.components.agents.gateway.client import get_gateway_client

    work_id = deterministic_work_id(
        source=str(trigger.get("trigger-id", "event-trigger")),
        delivery_id=delivery_id,
    )
    result = get_gateway_client(project_root).submit_agent_work(
        project_root,
        context_id,
        {
            "message_id": f"event:{delivery_id}",
            "text": prompt,
            "inputs": {"event-type": event_type, "payload": dict(payload)},
            "created_at": f"event:{delivery_id}",
        },
        work_id=work_id,
    )
    return get_work(project_root, result["work_id"])
