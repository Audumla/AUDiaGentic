"""Event-to-Work ingress primitives for the Slice 6 trigger migration."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contracts import AgentWorkRecord, WorkInputMessage
from .service import submit_work


def deterministic_work_id(*, source: str, delivery_id: str) -> str:
    """Derive one stable Work identity for an event delivery."""
    digest = hashlib.sha256(f"{source}\0{delivery_id}".encode()).hexdigest()[:24]
    return f"work_evt_{digest}"


def submit_event_work(
    project_root: Path,
    *,
    context_id: str,
    source: str,
    delivery_id: str,
    text: str,
    inputs: dict[str, Any] | None = None,
) -> AgentWorkRecord:
    """Submit one replay-safe event delivery through canonical Work."""
    work_id = deterministic_work_id(source=source, delivery_id=delivery_id)
    return submit_work(
        project_root,
        context_id,
        WorkInputMessage(
            delivery_id,
            text,
            inputs or {},
            f"event:{source}:{delivery_id}",
        ),
        work_id=work_id,
    )
