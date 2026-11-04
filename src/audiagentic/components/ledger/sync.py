"""Ledger write lock and current-ledger validation.

Recording writes one write-once event file per event, so there is nothing to merge into a shared file any more;
this module keeps the lock that serializes release-time operations and a validation pass that reads every current
source through the one loader (so a malformed or conflicting event is reported, never skipped).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from audiagentic.components.ledger.current_events import pending_events
from audiagentic.components.ledger.paths import ledger_lock_path
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.process import StartupLock


@dataclass(frozen=True)
class SyncResult:
    pending_count: int
    warning: str | None


def _acquire_lock(project_root: Path) -> tuple[StartupLock, str | None]:
    lock_path = ledger_lock_path(project_root)
    warning = "stale-lock-replaced" if lock_path.exists() else None
    lock = StartupLock(lock_path, timeout=0.1)
    try:
        lock.__enter__()
    except AudiaGenticError as exc:
        if exc.code == "TO-PROC-002":
            raise AudiaGenticError(
                code="CON-SYNCL-001",
                kind="release",
                message="sync lock already held",
                details={"path": str(lock_path)},
            ) from exc
        raise
    return lock, warning


def _release_lock(lock: StartupLock) -> None:
    lock.__exit__()


@contextmanager
def ledger_write_lock(project_root: Path):
    """Hold the ledger lock across a complete authoritative operation."""
    lock, warning = _acquire_lock(project_root)
    try:
        yield warning
    finally:
        _release_lock(lock)


def check_current_ledger(project_root: Path) -> SyncResult:
    """Deliver pending projection intents, then validate every current source and count the pending events."""
    from audiagentic.components.ledger.event_outbox import drain as drain_event_outbox

    drain_event_outbox(project_root)
    with ledger_write_lock(project_root) as warning:
        return SyncResult(pending_count=len(pending_events(project_root)), warning=warning)
