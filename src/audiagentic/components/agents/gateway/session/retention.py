"""Retention lineage facts for gateway execution records (AS107)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audiagentic.components.agents.agents_paths import (
    gateway_request_dir,
    gateway_retention_lock_path,
)
from audiagentic.foundation.system.process import StartupLock

from .sessions_store import list_session_records


@dataclass(frozen=True)
class RequestRetentionPin:
    """A redacted answer to whether deleting an execution record is unsafe."""

    pinned: bool
    reason: str | None = None


def _request_retention_pin_unlocked(project_root: Path, request_id: str) -> RequestRetentionPin:
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
    # A durable runtime root can contain provider/session continuation state
    # even when its volatile process or browser handle is gone. Presence of
    # the root is therefore a positive retention dependency, not liveness
    # evidence and never an automatic release signal.
    runtime_root = gateway_request_dir(project_root, request_id) / "runtime"
    try:
        if runtime_root.is_dir() and any(runtime_root.iterdir()):
            return RequestRetentionPin(True, "durable-runtime-root")
    except OSError:
        # An unreadable root is conservatively pinned; purge must not infer
        # that inaccessible state is safe to remove.
        return RequestRetentionPin(True, "durable-runtime-root")
    return RequestRetentionPin(False)


def request_retention_pin(project_root: Path, request_id: str) -> RequestRetentionPin:
    """Read retention state under the same fence used by purge."""
    with StartupLock(gateway_retention_lock_path(project_root)):
        return _request_retention_pin_unlocked(project_root, request_id)


__all__ = ["RequestRetentionPin", "request_retention_pin", "_request_retention_pin_unlocked"]
