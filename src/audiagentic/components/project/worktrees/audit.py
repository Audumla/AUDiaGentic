"""Append-only audit trail of worktree provenance events (DW03).

One JSON line per event in the user state directory, next to the owner records and outside
every worktree. It outlives the record: finishing and forgetting a worktree never touches it.
The finish journal stays the authority for crash recovery, so a failed append is logged and
never refuses or undoes the action it describes.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system.advisory_lock import AdvisoryLock
from audiagentic.foundation.time import now_iso_z

from . import records

logger = logging.getLogger(__name__)
audit_error = make_error_factory("VAL", "WTAUD", "project")


def _path(repo: Path, state_root: Path | None) -> Path:
    return (state_root or user_state_dir()) / "worktrees" / "audit" / f"{records.repo_id(repo)}.jsonl"


def append(repo: Path, action: str, *, state_root: Path | None = None, **fields: Any) -> None:
    """Record one event; never raises."""
    try:
        path = _path(repo, state_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": now_iso_z(), "action": action, **fields}, sort_keys=True, default=str)
        with AdvisoryLock(path.with_suffix(".lock")):
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    except Exception:  # noqa: BLE001 - the audit trail must not stop the action it describes
        logger.warning("worktree audit event %s could not be written", action, exc_info=True)


def read(repo: Path, *, state_root: Path | None = None) -> list[dict[str, Any]]:
    """Every event, oldest first. A damaged line raises: the log is never silently read as shorter."""
    path = _path(repo, state_root)
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            events.append(json.loads(line))
        except ValueError as error:
            raise audit_error(1, "The worktree audit log has a damaged line", file=path.name, line=number) from error
    return events
