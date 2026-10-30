"""Bringing a task branch up to date without rewriting it (DW01 ``worktree sync``).

Local git only; nothing is pushed. It fetches the remote default branch and this branch, then
fast-forwards to the remote copy of the branch when that is strictly ahead (for example after the
forge updated a pull request's branch), and merges the default branch in when the branch is behind
it. It never rebases, never resets, never forces and never resolves a conflict: a conflict or a
diverged remote branch aborts and leaves the worktree exactly as it was.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system import git
from audiagentic.foundation.system.advisory_lock import AdvisoryLock

from . import records, service
from .eligibility import ActiveWork

refuse_error = make_error_factory("CON", "WTSYNC", "project")


def _blockers(repo: Path, entry: git.WorktreeEntry, head: str | None, active_work: ActiveWork) -> list[str]:
    reasons: list[str] = []
    if entry.path in service.protected_paths(repo):
        reasons.append("protected: this worktree is declared protected")
    if entry.branch is None:
        reasons.append("detached-head: a detached HEAD has no branch to update")
    tip = entry.head or ""
    if head is not None and (len(head) < 12 or not tip.startswith(head)):
        reasons.append(f"head-mismatch: the tip is {tip[:12]}, not the {head} you confirmed")
    tracked, untracked = git.changes(entry.path)
    if tracked or untracked:
        reasons.append(f"uncommitted-changes: {tracked} tracked change(s), {untracked} untracked")
    operation = git.operation_in_progress(entry.path)
    if operation:
        reasons.append(f"{operation}-in-progress: finish or abort the {operation} already under way")
    try:
        active = active_work(entry.path)
        if not isinstance(active.get("requests"), list) or not isinstance(active.get("sessions"), list):
            raise ValueError("malformed active-work reply")
        if active["requests"] or active["sessions"]:
            reasons.append("gateway-active-work: unfinished gateway requests or sessions in this worktree")
    except Exception:  # noqa: BLE001 - an unreadable store is never "empty"
        reasons.append("active-work-unreadable: gateway records could not be read")
    return reasons


def _fetch(repo: Path, remote: str, base_branch: str, branch: str) -> str | None:
    """Fetch the default branch and this branch; the commit the remote branch has, or ``None`` if it has none."""
    try:
        git.fetch(repo, remote, base_branch)
    except Exception as error:
        raise refuse_error(5, "Could not fetch the remote default branch; refusing to judge against a stale one") from error
    try:
        on_remote = git.remote_branch_commit(repo, remote, branch)
    except Exception as error:
        raise refuse_error(5, "The remote branch could not be read; refusing to guess whether it exists") from error
    if on_remote is None:
        return None  # positively absent: the branch has not been pushed yet
    try:
        git.fetch(repo, remote, branch)
    except Exception as error:
        raise refuse_error(5, "The remote branch exists but could not be fetched; refusing to use a stale copy") from error
    if git.resolve_commit(repo, f"refs/remotes/{remote}/{branch}") != on_remote:
        raise refuse_error(5, "The fetched branch is not the commit the remote reported; try again")
    return on_remote


def sync(repo: Path, path: Path, *, head: str | None = None, active_work: ActiveWork,
         dry_run: bool = False, state_root: Path | None = None) -> dict[str, Any]:
    """Bring ``path``'s branch up to date with the remote copy and the default branch, or refuse."""
    entries = git.list_worktrees(repo)
    entry = next((e for e in entries if e.path == path), None)
    if entry is None or entry == entries[0]:
        raise refuse_error(1, "That path is not a task worktree of this repository", path=str(path))
    base = git.default_branch(repo)
    if base is None:
        raise refuse_error(1, "The remote default branch is unknown; there is nothing to bring the branch up to date with")
    remote, _, base_branch = base.partition("/")
    if entry.branch == base_branch:
        raise refuse_error(1, "The default branch is not a task branch and is never synced here")
    lock = (state_root or user_state_dir()) / "worktrees" / f"{records.repo_id(repo)}.sync.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with AdvisoryLock(lock, timeout=60.0):
        reasons = _blockers(repo, entry, head, active_work)
        if reasons:
            raise refuse_error(1, "This worktree cannot be synced: " + "; ".join(reasons[:4]), blockers=reasons)
        before = entry.head or ""
        branch = entry.branch or ""
        remote_tip = _fetch(repo, remote, base_branch, branch) if not dry_run \
            else git.resolve_commit(repo, f"refs/remotes/{remote}/{branch}")

        # Plan everything first; nothing is touched until every question has an answer.
        fast_forward = False
        effective = before
        if remote_tip and remote_tip != before:
            behind_remote = git.is_ancestor(repo, before, remote_tip)
            ahead_of_remote = git.is_ancestor(repo, remote_tip, before)
            if behind_remote is None or ahead_of_remote is None:
                raise refuse_error(5, "The relationship between the branch and its remote copy cannot be established; "
                                      "nothing was changed")
            if behind_remote:
                fast_forward, effective = True, remote_tip
            elif not ahead_of_remote:
                raise refuse_error(2, f"{branch} and {remote}/{branch} have diverged; reconcile them yourself "
                                      "(nothing was changed)", local=before[:12], remote=remote_tip[:12])
        behind = git.commits_not_in(repo, base, effective)  # commits of the default branch the branch lacks
        if behind is None:
            raise refuse_error(5, "The distance to the default branch cannot be established; nothing was changed")
        actions = ([f"fast-forward to {remote}/{branch} ({effective[:12]})"] if fast_forward else [])
        actions += [f"merge {base} ({behind} commit(s) behind)"] if behind else []
        if dry_run or not actions:
            return _result(entry, before, before, dry_run, actions)

        if fast_forward:
            git.merge_fast_forward(entry.path, f"refs/remotes/{remote}/{branch}")
            if git.resolve_commit(entry.path, "HEAD") != effective:
                raise refuse_error(4, "The fast-forward did not land where planned; inspect the worktree", before=before[:12])
        if behind:
            try:
                git.merge_ref(entry.path, base)
            except Exception as error:
                conflicts = git.conflicted_paths(entry.path) if git.merge_in_progress(entry.path) else []
                try:
                    if git.merge_in_progress(entry.path):
                        git.merge_abort(entry.path)
                except Exception as abort_error:  # noqa: BLE001
                    raise refuse_error(4, "The merge failed and could not be aborted; run `git merge --abort` in the "
                                          "worktree", path=str(entry.path), before=before[:12]) from abort_error
                restored = (git.resolve_commit(entry.path, "HEAD") == effective and git.changes(entry.path) == (0, 0)
                            and git.operation_in_progress(entry.path) is None)
                if not restored:
                    raise refuse_error(4, "The merge failed and the worktree is not exactly as it was; inspect it "
                                          "before continuing", path=str(entry.path), before=before[:12],
                                       expected=effective[:12]) from error
                where = "" if effective == before else f" (the fast-forward to {effective[:12]} had already happened)"
                if conflicts:
                    raise refuse_error(3, f"Merging {base} conflicts in {len(conflicts)} file(s): "
                                          + ", ".join(conflicts[:5]) + f"; the merge was aborted{where}",
                                       conflicts=conflicts) from error
                raise refuse_error(4, "git could not complete the merge (for example no committer identity is "
                                      f"configured); the merge did not happen{where}",
                                   reason=getattr(error, "details", None)) from error
        return _result(entry, before, git.resolve_commit(entry.path, "HEAD") or before, False, actions)


def _result(entry: git.WorktreeEntry, before: str, after: str, dry_run: bool, actions: list[str]) -> dict[str, Any]:
    return {"worktree": str(entry.path), "branch": entry.branch, "before": before, "after": after, "dry-run": dry_run,
            "estimate": dry_run, "actions": actions, "changed": bool(actions) and not dry_run,
            "next": "publish the new tip with `audiagentic worktree merge` (or `push`)" if actions and not dry_run else None}
