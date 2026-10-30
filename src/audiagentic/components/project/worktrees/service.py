"""Read-only worktree listing and primary-checkout verification (DW01)."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from audiagentic.foundation.config.settings import resolve_settings_cached
from audiagentic.foundation.system import git
from audiagentic.foundation.system.process import pids_referencing_path

from . import records


def protected_paths(repo: Path) -> dict[Path, str]:
    """Canonical path to name for every worktree the project declares protected."""
    declared = resolve_settings_cached(repo).get("worktrees.protected") or {}
    return {Path(path).expanduser().resolve(): name for name, path in declared.items()}


def _age_hours(created_at: str | None) -> float | None:
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    return round(max(0.0, time.time() - created) / 3600, 1)


def list_rows(repo: Path, *, state_root: Path | None = None) -> dict[str, Any]:
    """Every worktree of the repository with its facts, plus records that no longer match git.

    ``pr`` stays ``None`` here: pull-request state needs the forge adapter, and
    an unknown is reported as unknown rather than guessed.
    """
    entries = git.list_worktrees(repo)
    reconciliation = records.reconcile(entries, records.read_records(repo, state_root=state_root))
    base = git.default_branch(repo)
    protected = protected_paths(repo)
    rows = []
    for index, entry in enumerate(entries):
        record = reconciliation.paired.get(entry.path)
        ahead_behind = git.ahead_behind(entry.path, base) if base and not entry.bare else None
        tracked, untracked = (0, 0) if entry.bare or entry.prunable else git.changes(entry.path)
        users = None if entry.prunable else pids_referencing_path(entry.path)
        rows.append({
            "path": str(entry.path),
            "primary": index == 0,
            "branch": entry.branch,
            "head": entry.head,
            "detached": entry.branch is None and not entry.bare,
            "locked": entry.locked,
            "prunable": entry.prunable,
            "protected": protected.get(entry.path),
            "changes": tracked,
            "untracked": untracked,
            "ahead": None if ahead_behind is None else ahead_behind[0],
            "behind": None if ahead_behind is None else ahead_behind[1],
            "owner": record.owner if record else None,
            "purpose": record.purpose if record else None,
            "plan-item": record.plan_item if record else None,
            "age-hours": _age_hours(record.created_at) if record else None,
            "managed": record is not None,
            "processes": users,  # None = this platform cannot tell
            "pr": None,
        })
    return {
        "repo-id": records.repo_id(repo),
        "default-branch": base,
        "worktrees": rows,
        "orphan-records": [{"worktree-id": r.worktree_id, "path": r.path, "branch": r.branch}
                           for r in reconciliation.orphans],
    }


def primary_checkout_problems(repo: Path) -> list[str]:
    """Why the main worktree is not a clean base: off the default branch, behind, or diverged."""
    entries = git.list_worktrees(repo)
    if not entries:
        return []
    primary = entries[0]
    base = git.default_branch(repo)
    if base is None:
        return ["the remote default branch is unknown (no origin/HEAD, origin/main or origin/master ref)"]
    expected = base.split("/", 1)[-1]
    problems = []
    if primary.branch != expected:
        problems.append(f"the main worktree is on {primary.branch or 'a detached HEAD'}, not {expected}")
    relation = git.ahead_behind(primary.path, base)
    if relation is not None and primary.branch == expected:
        ahead, behind = relation
        if ahead and behind:
            problems.append(f"{expected} has diverged from {base} ({ahead} ahead, {behind} behind)")
        elif ahead:
            problems.append(f"{expected} is {ahead} commits ahead of {base}")
        elif behind:
            problems.append(f"{expected} is {behind} commits behind {base}")
    return problems
