"""Retention lineage facts for gateway execution records (AS107)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .sessions_store import list_session_records


@dataclass(frozen=True)
class RequestRetentionPin:
    """A redacted answer to whether deleting an execution record is unsafe."""

    pinned: bool
    reason: str | None = None


def request_retention_pin(project_root: Path, request_id: str) -> RequestRetentionPin:
    """Pin records referenced by a durable session lineage.

    A provider continuation can depend on the originating request runtime even
    after its browser tab/process has gone away.  The binding itself remains
    private; this API exposes only the boolean safety fact and a stable reason.
    """
    for record in list_session_records(project_root):
        activity = record.get("activity")
        request_ids = activity.get("request-ids") if isinstance(activity, dict) else None
        if isinstance(request_ids, list) and request_id in request_ids:
            return RequestRetentionPin(True, "session-lineage-reference")
    return RequestRetentionPin(False)


__all__ = ["RequestRetentionPin", "request_retention_pin"]
