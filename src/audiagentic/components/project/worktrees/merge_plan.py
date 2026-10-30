"""What ``worktree merge`` would do, and what stops it (DW01 slice 4a, read-only).

Builds a plan from git, the forge and the gateway's active-work query, and never
pushes, fetches, creates, updates or writes anything. A fact it cannot establish is
an ``unknown`` blocker, and unknown refuses exactly like blocked, so a later
executing slice can reuse this verbatim as its precondition check. The pull request
is identified strictly: this repository, this exact head branch, the default branch
as base. A closed unmerged pull request is never replaced by a new one.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.system import forge, git

from . import service
from .eligibility import ActiveWork, Blocker

refuse_error = make_error_factory("CON", "WTMERGE", "project")

TITLE_PATTERN = re.compile(r"(feat|fix|docs|chore|refactor|test|perf|ci|build|revert)(\([^)\s][^)]*\))?!?: \S.*")
TITLE_LIMIT = 100

PullRequests = Callable[[Path, str], tuple[forge.PullRequest, ...]]
Identity = Callable[[Path], forge.RepositoryIdentity]

_URL = re.compile(r"^(?:[a-z+]+://)?(?:[^@/]+@)?[^/:]+[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$")


def repository_slug(url: str | None) -> str | None:
    """``owner/name`` from an https, ssh or scp-style remote URL; credentials are ignored, never returned."""
    match = _URL.match((url or "").strip())
    return f"{match['owner']}/{match['name']}".lower() if match else None


def title_problem(title: str) -> str | None:
    if len(title) > TITLE_LIMIT:
        return f"longer than {TITLE_LIMIT} characters"
    if not TITLE_PATTERN.fullmatch(title):
        return "not a conventional commit title (type(scope): subject)"
    return None


def _remote_blockers(repo: Path, identity: forge.RepositoryIdentity | None) -> list[Blocker]:
    fetch, push = repository_slug(git.remote_url(repo)), repository_slug(git.remote_url(repo, push=True))
    if fetch is None or push is None:
        return [Blocker("remote-unreadable", "origin is missing or its URL is not a recognised repository URL")]
    if fetch != push:
        return [Blocker("remote-mismatch", "origin fetches from one repository and pushes to another")]
    if identity is not None and identity.name_with_owner.lower() != fetch:
        return [Blocker("remote-not-this-repository",
                        f"origin points at {fetch}, the forge reports this repository as {identity.name_with_owner}")]
    return []


def _pull_request_plan(found: tuple[forge.PullRequest, ...], branch: str, tip: str, default: str,
                       title: str | None) -> tuple[list[Blocker], list[dict[str, str]], forge.PullRequest | None]:
    own = [pr for pr in found if not pr.cross_repository and pr.head_branch == branch]
    opened = [pr for pr in own if pr.state == "OPEN"]
    blockers: list[Blocker] = []
    operations: list[dict[str, str]] = []
    if len(opened) > 1:
        return [Blocker("pr-ambiguous", "several open pull requests have this branch as head: "
                        + ", ".join(f"#{pr.number}" for pr in opened), True)], operations, None
    if not opened:
        if any(pr.state == "MERGED" and pr.head_sha == tip for pr in own):
            return [Blocker("already-merged", "a pull request with this exact tip is already merged")], operations, None
        if any(pr.state == "CLOSED" for pr in own):
            blockers.append(Blocker("closed-pr-exists", "a closed unmerged pull request exists for this branch; "
                                    "reopen it or use a new branch (a replacement is never created silently)"))
        if title is None:
            blockers.append(Blocker("title-required", "no pull request exists; give title TEXT to create one"))
        elif (problem := title_problem(title)):
            blockers.append(Blocker("title-invalid", f"title is {problem}"))
        operations.append({"step": "pull-request", "action": "create", "detail": f"base {default}"})
        operations.append({"step": "auto-merge", "action": "enable squash auto-merge", "detail": "after the pull request exists"})
        return blockers, operations, None
    pr = opened[0]
    if pr.is_draft:
        blockers.append(Blocker("pr-draft", f"#{pr.number} is a draft"))
    if pr.base != default:
        blockers.append(Blocker("pr-wrong-base", f"#{pr.number} targets {pr.base}, not {default}"))
    if title is not None:
        if (problem := title_problem(title)):
            blockers.append(Blocker("title-invalid", f"title is {problem}"))
        operations.append({"step": "pull-request", "action": f"reuse #{pr.number} and set its title", "detail": pr.url})
    else:
        operations.append({"step": "pull-request", "action": f"reuse #{pr.number}", "detail": pr.url})
    if pr.auto_merge:
        operations.append({"step": "auto-merge", "action": "already enabled", "detail": f"#{pr.number}"})
    else:
        operations.append({"step": "auto-merge", "action": "enable squash auto-merge", "detail": f"#{pr.number}"})
    if pr.merge_state == "BEHIND":
        operations.append({"step": "report", "action": "pull request is BEHIND the default branch",
                           "detail": "merge never updates the branch; sync it first"})
    return blockers, operations, pr


def plan(repo: Path, path: Path, *, title: str | None = None, head: str | None = None, active_work: ActiveWork,
         pull_requests: PullRequests = forge.pull_requests_for_branch,
         identity: Identity = forge.repository_identity) -> dict[str, Any]:
    """The would-be steps for the worktree at ``path``, with every blocker; nothing is changed."""
    entries = git.list_worktrees(repo)
    entry = next((e for e in entries if e.path == path), None)
    blockers: list[Blocker] = []
    if entry is None or entry == entries[0]:
        raise refuse_error(1, "That path is not a task worktree of this repository", path=str(path))
    if entry.path in service.protected_paths(repo):
        blockers.append(Blocker("protected", "this worktree is declared protected"))
    if entry.branch is None:
        blockers.append(Blocker("detached-head", "a detached HEAD has no branch to push"))
    base = git.default_branch(repo)
    default = base.split("/", 1)[-1] if base else None
    if entry.branch is not None and entry.branch == default:
        blockers.append(Blocker("default-branch", "the default branch is never pushed from a task worktree"))
    tip = entry.head or ""
    if head is not None and (len(head) < 12 or not tip.startswith(head)):
        blockers.append(Blocker("head-mismatch", f"the tip is {tip[:12]}, not the {head} you confirmed"))
    try:
        tracked, untracked = git.changes(entry.path)
        if tracked or untracked:
            blockers.append(Blocker("uncommitted-changes", f"{tracked} tracked change(s), {untracked} untracked"))
        if git.initialized_submodules(entry.path):
            blockers.append(Blocker("submodules", "initialized submodules are not pushed by this command"))
    except Exception as error:  # noqa: BLE001 - git could not say: refuse
        blockers.append(Blocker("git-unreadable", f"worktree state could not be read ({getattr(error, 'code', type(error).__name__)})", True))
    ahead = git.commits_not_in(repo, tip, base) if base else None
    if ahead == 0:
        blockers.append(Blocker("nothing-to-merge", f"no commits that are not already on {base}"))
    elif ahead is None:
        blockers.append(Blocker("default-branch-unknown", "the remote default branch is not known locally", True))
    try:
        active = active_work(entry.path)
        if not isinstance(active.get("requests"), list) or not isinstance(active.get("sessions"), list):
            raise ValueError("malformed active-work reply")
        if active["requests"] or active["sessions"]:
            blockers.append(Blocker("gateway-active-work", "unfinished gateway requests or sessions in this worktree"))
    except Exception as error:  # noqa: BLE001 - an unreadable store is never "empty"
        blockers.append(Blocker("active-work-unreadable", f"gateway records could not be read ({getattr(error, 'code', type(error).__name__)})", True))

    operations: list[dict[str, str]] = []
    found_pr = None
    try:
        who = identity(repo)
    except Exception as error:  # noqa: BLE001
        who = None
        blockers.append(Blocker("forge-unavailable", f"repository details could not be read ({getattr(error, 'code', type(error).__name__)})", True))
    blockers.extend(_remote_blockers(repo, who))
    if who is not None and not who.can_push:
        blockers.append(Blocker("no-push-permission", f"you cannot push to {who.name_with_owner}"))
    if who is not None and default is not None and who.default_branch != default:
        blockers.append(Blocker("default-branch-mismatch", f"the forge's default branch is {who.default_branch}, local origin/HEAD says {default}"))
    if entry.branch and default:
        try:
            found = pull_requests(repo, entry.branch)
            more, operations, found_pr = _pull_request_plan(found, entry.branch, tip, default, title)
            blockers.extend(more)
        except Exception as error:  # noqa: BLE001
            blockers.append(Blocker("forge-unavailable", f"pull requests could not be read ({getattr(error, 'code', type(error).__name__)})", True))
    steps = [{"step": "pre-push-checks", "action": "none configured", "detail": "user-scope check mapping arrives in a later slice"},
             {"step": "push", "action": f"git push origin {tip[:12]}:refs/heads/{entry.branch}", "detail": "non-force, explicit commit"}]
    verdict = "blocked" if any(not b.unknown for b in blockers) else "unknown" if blockers else "ready"
    return {"worktree": str(entry.path), "branch": entry.branch, "tip": tip, "default-branch": default,
            "repository": who.name_with_owner if who else None, "verdict": verdict,
            "blockers": [b.to_dict() for b in blockers], "operations": steps + operations,
            "pr": None if found_pr is None else found_pr.number, "dry-run": True}

