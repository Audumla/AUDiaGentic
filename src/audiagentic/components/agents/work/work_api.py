"""Public Work application boundary for protocol adapters."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audiagentic.foundation.interaction.api import respond

from .contracts import WorkInputMessage
from .event_adapter import dispatch_trigger_event
from .event_failures import read_event_failures
from .ingress import deterministic_work_id
from .reviews import review_work_id
from .service import add_work_message, cancel_work, get_work, list_work


def submit_child(
    project_root: Path,
    parent_work_id: str,
    *,
    message_id: str,
    text: str,
    inputs: dict[str, Any] | None = None,
    target_agent_id: str | None = None,
    timeout_seconds: float | None = None,
    work_id: str | None = None,
) -> dict[str, Any]:
    from audiagentic.components.agents.gateway.client import get_gateway_client
    return get_gateway_client(project_root).submit_agent_work_child(
        project_root,
        parent_work_id,
        {"message_id": message_id, "text": text, "inputs": inputs or {}, "created_at": f"api:{message_id}"},
        work_id=work_id,
        target_agent_id=target_agent_id,
        timeout_seconds=timeout_seconds,
    )


def submit_packet(
    project_root: Path,
    *,
    context_id: str,
    packet_id: str,
    text: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit one deterministic packet Work; no packet/job state machine is created."""
    work_id = deterministic_work_id(source="packet", delivery_id=packet_id)
    from audiagentic.components.agents.gateway.client import get_gateway_client
    record = get_gateway_client(project_root).submit_agent_work(
        project_root,
        context_id,
        {
            "message_id": f"packet:{packet_id}",
            "text": text,
            "inputs": {"packet-id": packet_id, **dict(metadata or {})},
            "created_at": f"packet:{packet_id}",
        },
        work_id=work_id,
    )
    return record


def submit_trigger_event(
    project_root: Path,
    *,
    context_id: str,
    trigger: Mapping[str, Any],
    event_type: str,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
    prompt: str,
) -> dict[str, Any] | None:
    """Submit a matched event through the public canonical Work boundary."""
    record = dispatch_trigger_event(
        project_root,
        trigger=trigger,
        event_type=event_type,
        payload=payload,
        metadata=metadata,
        context_id=context_id,
        prompt=prompt,
    )
    return record.to_mapping() if record is not None else None


def submit_review(
    project_root: Path,
    parent_work_id: str,
    *,
    review_key: str,
    prompt: str,
) -> dict[str, Any]:
    """Submit/replay one deterministic review child Work."""
    return submit_child(
        project_root,
        parent_work_id,
        message_id=f"review:{review_key}",
        text=prompt,
        inputs={"review-key": review_key},
        work_id=review_work_id(parent_work_id, review_key),
    )


def get_status(project_root: Path, work_id: str) -> dict[str, Any]:
    """Read one Work record through the public application boundary."""
    return get_work(project_root, work_id).to_mapping()


def list_status(project_root: Path) -> list[dict[str, Any]]:
    """Read all project Work records through the public application boundary."""
    return [record.to_mapping() for record in list_work(project_root)]


def add_message(
    project_root: Path,
    work_id: str,
    *,
    message_id: str,
    text: str,
    inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one idempotent Work input message."""
    return add_work_message(
        project_root,
        work_id,
        WorkInputMessage(message_id, text, dict(inputs or {}), f"api:{message_id}"),
    ).to_mapping()


def cancel(project_root: Path, work_id: str) -> dict[str, Any]:
    """Cancel Work through the canonical Work control boundary."""
    return cancel_work(project_root, work_id).to_mapping()


def list_event_failures(project_root: Path) -> list[dict[str, Any]]:
    """Read canonical event-ingress failures through the public Work API."""
    return read_event_failures(project_root)


def overview(project_root: Path) -> dict[str, Any]:
    """Return a redacted read-only Work/event-ingress operational overview."""
    records = list_status(project_root)
    return {
        "work-count": len(records),
        "work-by-state": dict(sorted(Counter(record["state"] for record in records).items())),
        "event-failure-count": len(read_event_failures(project_root)),
    }


def answer(
    project_root: Path,
    work_id: str,
    *,
    choice: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer Work's Foundation interaction and resume it once."""
    work = get_work(project_root, work_id)
    interaction_id = work.current_interaction_id
    if not interaction_id:
        raise ValueError(f"Work {work_id!r} is not waiting on an interaction")
    respond(interaction_id, choice, details=dict(details or {}), project_root=project_root)
    resumed = __import__(
        "audiagentic.components.agents.work.interactions",
        fromlist=["resume_after_interaction"],
    ).resume_after_interaction(project_root, work_id)
    return (resumed or get_work(project_root, work_id)).to_mapping()
