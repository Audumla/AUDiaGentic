"""Bounded child-Work delegation seam."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import AgentWorkRecord, WorkInputMessage
from .service import submit_child_work

MAX_DELEGATION_DEPTH = 8


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    parent_work_id: str
    target_agent_id: str
    message: WorkInputMessage
    timeout_seconds: float | None = None


def delegate_child_work(
    project_root: Path,
    parent_work_id: str,
    *,
    message_id: str,
    text: str,
    inputs: dict | None = None,
    work_id: str | None = None,
    target_agent_id: str | None = None,
    timeout_seconds: float | None = None,
) -> AgentWorkRecord:
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("delegation timeout_seconds must be positive")
    return submit_child_work(
        project_root,
        parent_work_id,
        WorkInputMessage(message_id, text, inputs or {}, f"delegation:{message_id}"),
        work_id=work_id,
        delegation_target_agent_id=target_agent_id,
        delegation_timeout_seconds=timeout_seconds,
    )
