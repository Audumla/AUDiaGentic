"""Background-only maintenance for dated gateway trace segments."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

from audiagentic.components.agents.agents_paths import (
    gateway_request_maintenance_lock_path,
    gateway_retention_lock_path,
    gateway_root,
    gateway_session_maintenance_lock_path,
)
from audiagentic.foundation.io import iter_ndjson
from audiagentic.foundation.observability.journal_segments import (
    journal_lock,
    maintain_segments,
    prepare_append,
)
from audiagentic.foundation.system.process import StartupLock

from .operations.retention_policy import load_retention_policy
from .retention import _eligible_record, journal_max_bytes

logger = logging.getLogger(__name__)
_KINDS = {
    "timeline.ndjson": "timeline",
    "observations.ndjson": "observation",
    "recovery-actions.ndjson": "recovery",
}


def journal_retention_days() -> int | None:
    """Invalid policy disables deletion, never protection checks."""
    policy = load_retention_policy()
    if not policy.available and policy.policy_id == "invalid":
        return None
    return policy.journal_retention_days


def _session_deletable(project_root: Path, entry: Path) -> bool:
    try:
        record = json.loads((entry / "record.json").read_text(encoding="utf-8"))
        if record.get("session-id") != entry.name:
            return False
        if record.get("state") not in {"closed", "failed", "expired"}:
            return False
        provider = record.get("provider") or {}
        if (provider.get("metadata") or {}).get("unresolved-turn-pending"):
            return False
        activity = record.get("activity")
        if not isinstance(activity, dict) or not isinstance(activity.get("request-ids"), list):
            return False
        for request_id in activity.get("request-ids", []):
            if not isinstance(request_id, str) or Path(request_id).name != request_id:
                return False
            if (
                _eligible_record(
                    project_root, gateway_root(project_root) / request_id, retention_fence_held=True
                )
                is None
            ):
                return False
        return not record.get("recovery-required") and not record.get("retention-pinned")
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _unresolved_recovery(entry: Path) -> bool:
    pending: set[str] = set()
    for row in iter_ndjson(entry / "recovery-actions.ndjson"):
        if row.get("event") == "action-intent":
            action_id = row.get("action-attempt-id")
            if not isinstance(action_id, str):
                return True
            if row.get("disposition") in {None, "intent-persisted", "reconciliation-required"}:
                pending.add(action_id)
        elif row.get("event") == "action-result":
            outcome = str(row.get("outcome") or "unknown")
            if row.get("terminal") is True and outcome in {
                "reconciliation-completed",
                "abandon-accepted",
                "cleared-not-submitted",
                "success",
                "completed",
                "provider-resume-completed",
            }:
                pending.discard(row.get("action-attempt-id"))
    return bool(pending)


def maintain_project_journals(project_root: Path, *, now: datetime | None = None) -> dict[str, int]:
    """Do bounded lossless compression and protected segment expiry.

    This must run on the retention worker, not the provider/event loop. The
    retention fence is held through each journal's eligibility check/deletion.
    Active heads are rolled when maintenance sees a UTC date boundary, allowing
    an idle terminal request to expire without needing another provider event.
    """
    root = gateway_root(project_root)
    result = {"segments-compressed": 0, "segments-deleted": 0, "segment-temps-deleted": 0}
    if not root.is_dir():
        return result
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = load_retention_policy().max_batch_size
    entries = [
        (entry, False)
        for entry in root.iterdir()
        if entry.is_dir() and not entry.is_symlink() and entry.name.startswith("req_")
    ]
    sessions = root / "sessions"
    if sessions.is_dir() and not sessions.is_symlink():
        entries.extend(
            (entry, True)
            for entry in sessions.iterdir()
            if entry.is_dir() and not entry.is_symlink() and entry.name.startswith("ses_")
        )
    for entry, is_session in sorted(entries):
        for name, kind in _KINDS.items():
            if remaining <= 0:
                return result
            path = entry / name
            if not path.exists() and not path.with_name(path.name + ".segments").exists():
                continue
            try:
                external = (
                    gateway_session_maintenance_lock_path
                    if is_session
                    else gateway_request_maintenance_lock_path
                )(project_root, entry.name)
                with StartupLock(external):
                    if not (entry / "record.json").is_file():
                        continue
                    with ExitStack() as fences:
                        # Match lifecycle's request -> retention -> session
                        # order. New recovery claims cannot race deletion.
                        if not is_session:
                            fences.enter_context(StartupLock(entry / "mutation.lock"))
                        fences.enter_context(StartupLock(gateway_retention_lock_path(project_root)))
                        if is_session:
                            fences.enter_context(StartupLock(entry / "mutation.lock"))
                        eligible = (
                            _session_deletable(project_root, entry)
                            if is_session
                            else _eligible_record(project_root, entry, retention_fence_held=True)
                            is not None
                            and not _unresolved_recovery(entry)
                        )
                        index = path.with_suffix(".index.ndjson")
                        with journal_lock(path):
                            prepare_append(path, index, max_bytes=journal_max_bytes(kind), now=now)
                        # Recovery journals enforce idempotency/retry budgets
                        # even after terminal resolution. They are durable
                        # request control state, not expiring raw traces.
                        days = journal_retention_days()  # Revalidate policy at deletion boundary.
                        expiry = (
                            (now - timedelta(days=days)).timestamp()
                            if eligible and kind != "recovery" and days is not None
                            else None
                        )
                        summary = maintain_segments(
                            path, delete_before=expiry, max_operations=remaining, compress=False
                        )
                    result["segments-deleted"] += summary["deleted"]
                    result["segment-temps-deleted"] += summary["temporary-deleted"]
                    remaining -= sum(summary.values())
                    # Gzip must not hold lifecycle or journal writer locks.
                    # The external fence alone prevents purge while copying.
                    if remaining:
                        summary = maintain_segments(
                            path, delete_before=None, max_operations=remaining
                        )
                        result["segments-compressed"] += summary["compressed"]
                        result["segment-temps-deleted"] += summary["temporary-deleted"]
                        remaining -= sum(summary.values())
            except (OSError, ValueError, TypeError):
                logger.warning(
                    "gateway segment maintenance deferred",
                    extra={"journal-kind": kind},
                    exc_info=True,
                )
    return result
