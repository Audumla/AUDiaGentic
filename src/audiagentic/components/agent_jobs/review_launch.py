"""Compatibility adapter for the retired review-job launcher.

Review lifecycle ownership is canonical Agents Work.  This module remains
temporarily so older prompt callers receive the same entry point, but it does
not execute providers, create review records, or write agent-jobs stores.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agents.work.work_api import submit_review
from audiagentic.foundation.contracts.errors import AudiaGenticError


def launch_review_request(project_root: Path, request: dict[str, Any], *, now_fn=None) -> dict[str, Any]:
    """Submit one deterministic review child Work for a canonical parent."""
    del now_fn
    parent_work_id = request.get("parent-work-id") or request.get("work-id")
    if not isinstance(parent_work_id, str) or not parent_work_id:
        raise AudiaGenticError(
            code="VAL-AGW-REVIEW-001",
            kind="agents",
            message="review launch requires a canonical parent work-id",
        )
    prompt_id = str(request.get("prompt-id", "review"))
    source = request.get("source") if isinstance(request.get("source"), dict) else {}
    reviewer_key = ":".join(
        str(source.get(key) or "") for key in ("provider-id", "surface", "session-id")
    ).strip(":")
    review_key = f"{prompt_id}:{reviewer_key or 'default'}"
    prompt = str(request.get("prompt-body") or "Review the parent Work.")
    child = submit_review(
        project_root,
        parent_work_id,
        review_key=review_key,
        prompt=prompt,
    )
    return {"status": "submitted", "work-id": child["work_id"], "parent-work-id": parent_work_id}
