"""Public Work application boundary for protocol adapters."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .delegation import delegate_child_work
from .event_adapter import dispatch_trigger_event
from .reviews import submit_review_work


def submit_child(
    project_root: Path,
    parent_work_id: str,
    *,
    message_id: str,
    text: str,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return delegate_child_work(
        project_root,
        parent_work_id,
        message_id=message_id,
        text=text,
        inputs=inputs,
    ).to_mapping()


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
    return submit_review_work(
        project_root,
        parent_work_id,
        review_key=review_key,
        prompt=prompt,
    ).to_mapping()
