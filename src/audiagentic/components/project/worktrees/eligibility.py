"""Read-only verdict on whether a worktree may be finished (DW01 slice 3b).

Nothing here deletes or writes. Every fact comes from git, the forge, the
process table or the gateway's own active-work query, and a fact that cannot be
established is a blocker marked ``unknown``: uncertain state refuses, it is never
guessed. A worktree is ``eligible`` only when no blocker of either kind remains.
Merged work is proven by a pull request on this repository whose head equals the
local tip, whose state is MERGED into the default branch, and whose merge commit
is reachable from the fetched default branch (a squash merge leaves the branch
tip unreachable, so reachability of the tip proves nothing).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.paths.names import project_marker_path
from audiagentic.foundation.system import forge, git
from audiagentic.foundation.system.process import pids_referencing_path

from . import service

#: Caches git ignores that are safe to lose with the worktree.
DISPOSABLE_CACHES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"})

ActiveWork = Callable[[Path], dict[str, list[str]]]
PullRequests = Callable[[Path, str], tuple[forge.PullRequest, ...]]


@dataclass(frozen=True)
class Blocker:
    code: str
    detail: str
    unknown: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "unknown": self.unknown}


@dataclass(frozen=True)
class Assessment:
    path: Path
    branch: str | None
    head: str | None
    verdict: str  # eligible | blocked | unknown
    blockers: tuple[Blocker, ...]
    notes: tuple[str, ...] = ()
    pull_request: forge.PullRequest | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path), "branch": self.branch, "head": self.head, "verdict": self.verdict,
            "blockers": [blocker.to_dict() for blocker in self.blockers], "notes": list(self.notes),
            "pr": None if self.pull_request is None else self.pull_request.number,
        }


def _verdict(blockers: list[Blocker]) -> str:
    if any(not blocker.unknown for blocker in blockers):
        return "blocked"
    return "unknown" if blockers else "eligible"


def classify_ignored(path: Path, entries: list[str]) -> tuple[list[str], list[str], int]:
    """``(unknown ignored entries, disposable cache count, project record count)``.

    Everything under the project marker directory is gateway/runtime record
    state that ``finish`` archives before removal; it is never silently dropped.
    """
    marker = project_marker_path(path).relative_to(path).as_posix()
    unknown: list[str] = []
    records: list[str] = []
    caches = 0
    for entry in entries:
        name = entry.rstrip("/")
        if name.rsplit("/", 1)[-1] in DISPOSABLE_CACHES:
            caches += 1
        elif name == marker or name.startswith(marker + "/"):
            records.append(entry)
        else:
            unknown.append(entry)
    return unknown, records, caches


def _merge_proof(repo: Path, entry: git.WorktreeEntry, base: str | None,
                 pull_requests: PullRequests) -> tuple[list[Blocker], forge.PullRequest | None]:
    if base is None:
        return [Blocker("default-branch-unknown", "the remote default branch is not known locally", True)], None
    try:
        found = pull_requests(repo, entry.branch or "")
    except Exception as error:  # noqa: BLE001 - any failure to ask the forge is "unknown"
        code = getattr(error, "code", type(error).__name__)
        return [Blocker("forge-unavailable", f"pull-request state could not be read ({code})", True)], None
    own = [pr for pr in found if not pr.cross_repository and pr.head_branch == entry.branch]
    if not own:
        return [Blocker("unmerged", "no pull request exists for this branch")], None
    matching = [pr for pr in own if pr.head_sha == entry.head]
    if not matching:
        numbers = ", ".join(f"#{pr.number}" for pr in own)
        merged = [pr for pr in own if pr.state == "MERGED"]
        hint = (f"; if this branch is already merged, fast-forward it to the pull request head: "
                f"git fetch origin refs/pull/{merged[-1].number}/head && git merge --ff-only FETCH_HEAD") if merged else ""
        return [Blocker("tip-differs-from-pr", f"local tip is not the head of {numbers}; commits would be lost{hint}")], None
    if len(matching) > 1:
        numbers = ", ".join(f"#{pr.number}" for pr in matching)
        return [Blocker("pr-ambiguous", f"several pull requests share this tip: {numbers}", True)], None
    pr = matching[0]
    if pr.state != "MERGED":
        return [Blocker(f"pr-{pr.state.lower()}", f"#{pr.number} is {pr.state}, not merged")], pr
    if pr.base != base.split("/", 1)[-1]:
        return [Blocker("pr-wrong-base", f"#{pr.number} merged into {pr.base}, not {base.split('/', 1)[-1]}")], pr
    if not pr.merge_commit:
        return [Blocker("merge-commit-unknown", f"#{pr.number} reports no merge commit", True)], pr
    reachable = git.is_ancestor(repo, pr.merge_commit, base)
    if reachable is None:
        return [Blocker("merge-commit-not-fetched",
                        f"merge commit of #{pr.number} is not in the local {base}; fetch first", True)], pr
    if not reachable:
        return [Blocker("merge-commit-not-on-default", f"merge commit of #{pr.number} is not on {base}")], pr
    return [], pr


def assess_one(repo: Path, entry: git.WorktreeEntry, *, primary: bool, protected: dict[Path, str],
               base: str | None, active_work: ActiveWork, pull_requests: PullRequests) -> Assessment:
    blockers: list[Blocker] = []
    notes: list[str] = []
    if primary:
        blockers.append(Blocker("primary", "the main worktree is never removed"))
    if entry.bare:
        blockers.append(Blocker("bare", "a bare repository has no worktree to remove"))
    if entry.path in protected:
        blockers.append(Blocker("protected", f"declared protected as {protected[entry.path]}"))
    if entry.prunable:
        blockers.append(Blocker("missing-path", "the directory is gone; `git worktree prune` clears the entry"))
    if blockers:
        return Assessment(entry.path, entry.branch, entry.head, "blocked", tuple(blockers))
    if entry.locked:
        blockers.append(Blocker("git-locked", "git has this worktree locked"))
    if entry.branch is None:
        blockers.append(Blocker("detached-head", "a detached HEAD keeps commits no branch names"))

    try:
        tracked, untracked = git.changes(entry.path)
        if tracked:
            blockers.append(Blocker("uncommitted-changes", f"{tracked} tracked change(s)"))
        if untracked:
            blockers.append(Blocker("untracked-files", f"{untracked} untracked file(s) or directories"))
        submodules = git.initialized_submodules(entry.path)
        if submodules:
            blockers.append(Blocker("submodules", f"initialized submodule(s): {', '.join(submodules[:3])}"))
        unknown_ignored, record_entries, caches = classify_ignored(entry.path, git.ignored_entries(entry.path))
        runtime = len(record_entries)
        if unknown_ignored:
            shown = ", ".join(unknown_ignored[:3]) + (" ..." if len(unknown_ignored) > 3 else "")
            blockers.append(Blocker("ignored-files", f"{len(unknown_ignored)} ignored entr(ies): {shown}"))
        if runtime:
            notes.append(f"{runtime} project record location(s) to archive before removal")
        if caches:
            notes.append(f"{caches} disposable cache dir(s)")
    except Exception as error:  # noqa: BLE001 - git could not say: refuse
        blockers.append(Blocker("git-unreadable", f"worktree state could not be read ({getattr(error, 'code', type(error).__name__)})", True))

    users = pids_referencing_path(entry.path)
    if users is None:
        blockers.append(Blocker("processes-unknown", "this platform cannot list processes using the path", True))
    elif users:
        blockers.append(Blocker("in-use", f"{len(users)} process(es) use this path, this command included if run from inside it"))

    try:
        active = active_work(entry.path)
        requests, sessions = active.get("requests"), active.get("sessions")
        if not isinstance(requests, list) or not isinstance(sessions, list):
            raise ValueError("active-work reply lacks request and session lists")
        if requests or sessions:
            blockers.append(Blocker("gateway-active-work",
                                    f"{len(requests)} request(s), {len(sessions)} session(s) not finished"))
    except Exception as error:  # noqa: BLE001 - an unreadable store is never "empty"
        blockers.append(Blocker("active-work-unreadable", f"gateway records could not be read ({getattr(error, 'code', type(error).__name__)})", True))

    proof, pr = ([], None) if entry.branch is None else _merge_proof(repo, entry, base, pull_requests)
    blockers.extend(proof)
    return Assessment(entry.path, entry.branch, entry.head, _verdict(blockers), tuple(blockers), tuple(notes), pr)


def assess_all(repo: Path, *, active_work: ActiveWork,
               pull_requests: PullRequests = forge.pull_requests_for_branch) -> dict[str, Any]:
    """Assess every worktree of the repository; nothing is fetched, written or removed."""
    entries = git.list_worktrees(repo)
    base = git.default_branch(repo)
    protected = service.protected_paths(repo)
    results = [
        assess_one(repo, entry, primary=index == 0, protected=protected, base=base,
                   active_work=active_work, pull_requests=pull_requests)
        for index, entry in enumerate(entries)
    ]
    return {"default-branch": base, "worktrees": [result.to_dict() for result in results]}
