"""Review orchestration over canonical parent/child Work."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .contracts import AgentWorkRecord, WorkInputMessage
from .service import submit_child_work


def review_work_id(parent_work_id: str, review_key: str) -> str:
    digest = hashlib.sha256(f"{parent_work_id}\0{review_key}".encode()).hexdigest()[:24]
    return f"work_review_{digest}"


def submit_review_work(
    project_root: Path,
    parent_work_id: str,
    *,
    review_key: str,
    prompt: str,
) -> AgentWorkRecord:
    """Create/replay one deterministic review child Work."""
    message = WorkInputMessage(
        message_id=f"review:{review_key}",
        text=prompt,
        inputs={"review-key": review_key},
        created_at=f"review:{review_key}",
    )
    return submit_child_work(
        project_root,
        parent_work_id,
        message,
        work_id=review_work_id(parent_work_id, review_key),
    )
