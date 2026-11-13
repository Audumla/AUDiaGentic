"""Evidence holds and adoption of existing worktrees (DW03).

A hold lives in the owner record and is audited when set or cleared; `finish`, `tidy` and `prune`
refuse a held worktree and no argument overrides that. It is enforced by these commands only: plain
``git worktree remove`` cannot be stopped. Adoption records a worktree git already has, recording the
adopter honestly (``created_at`` is the adoption time, ``adopted`` is true).
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.source_control import git_api as git
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.system.advisory_lock import AdvisoryLock
from audiagentic.foundation.time import now_iso_z

from . import audit, lifecycle, records

invalid_error = make_error_factory("VAL", "WTPROV", "project")


def _record_for(repo: Path, path: Path, state_root: Path | None) -> records.WorktreeRecord:
    resolved = path.resolve()
    for record in records.read_records(repo, state_root=state_root).values():
        if Path(record.path).resolve() == resolved:
            return record
    raise invalid_error(1, "That worktree has no ownership record; adopt it first", path=str(resolved))


def set_evidence(repo: Path, path: Path, reason: str, *, state_root: Path | None = None) -> records.WorktreeRecord:
    reason = reason.strip()
    if not reason:
        raise invalid_error(2, "An evidence hold needs a reason")
    record = _record_for(repo, path, state_root)
    updated = records.update(repo, record.worktree_id, state_root=state_root, evidence=reason)
    audit.append(repo, "evidence-set", state_root=state_root, worktree_id=record.worktree_id,
                 path=record.path, branch=record.branch, reason=reason)
    return updated


def clear_evidence(repo: Path, path: Path, *, state_root: Path | None = None) -> records.WorktreeRecord:
    record = _record_for(repo, path, state_root)
    updated = records.update(repo, record.worktree_id, state_root=state_root, evidence=None)
    audit.append(repo, "evidence-cleared", state_root=state_root, worktree_id=record.worktree_id,
                 path=record.path, branch=record.branch, was=record.evidence)
    return updated


def adopt(repo: Path, path: Path, *, purpose: str, plan_item: str | None = None,
          owner: dict[str, str] | None = None, state_root: Path | None = None) -> records.WorktreeRecord:
    """Record an existing worktree that has no record."""
    purpose = purpose.strip()
    if not purpose:
        raise invalid_error(3, "Adopting a worktree needs a purpose")
    entries = git.list_worktrees(repo)
    resolved = path.resolve()
    entry = next((e for e in entries if e.path == resolved), None)
    if entry is None:
        raise invalid_error(4, "git does not list that path as a worktree of this repository", path=str(resolved))
    if entry == entries[0]:
        raise invalid_error(5, "The main worktree is never adopted", path=str(resolved))
    if not resolved.exists():
        raise invalid_error(6, "That worktree's directory is gone", path=str(resolved))
    adopter = {**lifecycle.default_owner(), **(owner or {})}
    state = state_root
    lock = (state or lifecycle.user_state_dir()) / "worktrees" / f"{records.repo_id(repo)}.start.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with AdvisoryLock(lock, timeout=60.0):
        if any(Path(r.path).resolve() == resolved for r in records.read_records(repo, state_root=state).values()):
            raise invalid_error(7, "That worktree already has an ownership record", path=str(resolved))
        record = records.WorktreeRecord(
            worktree_id=records.new_worktree_id(), path=str(resolved), branch=entry.branch, owner=adopter,
            created_at=now_iso_z(), purpose=purpose, plan_item=plan_item, adopted=True,
            adopted_by=adopter["account"])
        records.register(repo, record, state_root=state)
    audit.append(repo, "adopt", state_root=state, worktree_id=record.worktree_id, path=record.path,
                 branch=record.branch, tip=entry.head, owner=adopter, purpose=purpose, plan_item=plan_item)
    return record
