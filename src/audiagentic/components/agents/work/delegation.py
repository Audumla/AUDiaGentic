"""Bounded child-Work delegation seam."""
from __future__ import annotations

from pathlib import Path

from .contracts import AgentWorkRecord, WorkInputMessage
from .service import submit_child_work


def delegate_child_work(
    project_root: Path,
    parent_work_id: str,
    *,
    message_id: str,
    text: str,
    inputs: dict | None = None,
    work_id: str | None = None,
) -> AgentWorkRecord:
    return submit_child_work(
        project_root,
        parent_work_id,
        WorkInputMessage(message_id, text, inputs or {}, f"delegation:{message_id}"),
        work_id=work_id,
    )
