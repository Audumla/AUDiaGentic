"""Central worktree ownership records (DW01).

Records live in the user state directory, keyed by repository identity, never
inside a worktree: nothing shows in ``git status``, a bad removal cannot take
the record with it, and ``git worktree remove`` of a dirty tree is unaffected.
git stays authoritative for what exists; a record only says who owns it and
why. :func:`reconcile` pairs the two and reports what disagrees.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system import git
from audiagentic.foundation.system.advisory_lock import AdvisoryLock
from audiagentic.foundation.time import now_iso_z

record_error = make_error_factory("VAL", "WTREC", "project")

SCHEMA_VERSION = 1
_WORKTREE_ID = re.compile(r"wt_[0-9a-f]{12}")


@dataclass(frozen=True)
class WorktreeRecord:
    worktree_id: str
    path: str
    branch: str | None
    owner: dict[str, str]  # session, harness, account (descriptive; leases come with `start`)
    created_at: str
    purpose: str = ""
    plan_item: str | None = None


@dataclass(frozen=True)
class Reconciliation:
    """How git's worktrees and the central records line up."""

    paired: dict[Path, WorktreeRecord] = field(default_factory=dict)
    unmanaged: tuple[git.WorktreeEntry, ...] = ()  # in git, no record
    orphans: tuple[WorktreeRecord, ...] = ()  # recorded, gone from git


def repo_id(repo: Path) -> str:
    """Stable identity shared by a repository and all its worktrees (its git common directory)."""
    return hashlib.sha256(str(git.common_dir(repo)).encode("utf-8")).hexdigest()[:16]


def _store_path(identity: str, state_root: Path | None) -> Path:
    return (state_root or user_state_dir()) / "worktrees" / f"{identity}.json"


def new_worktree_id() -> str:
    import uuid

    return f"wt_{uuid.uuid4().hex[:12]}"


def read_records(repo: Path, *, state_root: Path | None = None) -> dict[str, WorktreeRecord]:
    """All records of the repository; a corrupt store raises rather than reading as empty."""
    path = _store_path(repo_id(repo), state_root)
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema-version"] != SCHEMA_VERSION:
            raise ValueError("schema-version")
        return {key: _record(key, value) for key, value in document["records"].items()}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise record_error(1, "Worktree ownership records are unreadable; refusing to treat them as empty",
                           file=path.name) from error


def _record(key: str, value: dict[str, Any]) -> WorktreeRecord:
    if not _WORKTREE_ID.fullmatch(key) or value["worktree_id"] != key:
        raise ValueError("worktree id")
    return WorktreeRecord(**value)


def register(repo: Path, record: WorktreeRecord, *, state_root: Path | None = None) -> None:
    """Add a record; a different record under the same id or path is a conflict."""
    if not _WORKTREE_ID.fullmatch(record.worktree_id):
        raise record_error(2, "Invalid worktree id", worktree_id=record.worktree_id)
    identity = repo_id(repo)
    path = _store_path(identity, state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with AdvisoryLock(path.with_suffix(".lock")):
        records = read_records(repo, state_root=state_root)
        for other in records.values():
            if other.worktree_id != record.worktree_id and other.path == record.path:
                raise record_error(3, "Another record already owns this worktree path", path=record.path)
        if records.get(record.worktree_id, record) != record:
            raise record_error(3, "A different record already exists for this worktree id",
                               worktree_id=record.worktree_id)
        records[record.worktree_id] = record
        _write(path, identity, records)


def forget(repo: Path, worktree_id: str, *, state_root: Path | None = None) -> bool:
    """Remove a record. Returns whether one existed."""
    identity = repo_id(repo)
    path = _store_path(identity, state_root)
    if not path.exists():
        return False
    with AdvisoryLock(path.with_suffix(".lock")):
        records = read_records(repo, state_root=state_root)
        if records.pop(worktree_id, None) is None:
            return False
        _write(path, identity, records)
        return True


def _write(path: Path, identity: str, records: dict[str, WorktreeRecord]) -> None:
    atomic_write_json(path, {
        "schema-version": SCHEMA_VERSION, "repo-id": identity, "updated-at": now_iso_z(),
        "records": {key: asdict(value) for key, value in sorted(records.items())},
    })


def reconcile(entries: tuple[git.WorktreeEntry, ...], records: dict[str, WorktreeRecord]) -> Reconciliation:
    """Pair git's worktrees with records by canonical path; git decides what exists."""
    by_path = {Path(record.path).resolve(): record for record in records.values()}
    paired = {entry.path: by_path[entry.path] for entry in entries if entry.path in by_path}
    unmanaged = tuple(entry for entry in entries if entry.path not in by_path)
    present = {entry.path for entry in entries}
    orphans = tuple(record for path, record in sorted(by_path.items()) if path not in present)
    return Reconciliation(paired, unmanaged, orphans)
