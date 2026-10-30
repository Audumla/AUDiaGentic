"""Publishing a worktree for merge: push, open or reuse the pull request, request auto-merge (DW01 slice 4c).

Built on ``merge_plan`` (every precondition and the strict pull-request identity rules) and
``publish`` (the checks and the commit-bound push). It never waits for CI and never merges
itself: it asks the forge to squash-merge when the required checks pass and returns. Every
step converges when run again: a tip already on the remote is not pushed twice, an existing
open pull request is reused, and auto-merge already on is left alone. Before auto-merge is
requested the pull request's head must equal the pushed commit, and the forge itself enforces that head
(``--match-head-commit``), so a push between the check and the request cannot be authorized. Every forge
call is pinned to this repository (owner/name). It never updates the branch
(a pull request that is behind is reported; that belongs to ``worktree sync``).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.config.settings import resolve_settings_cached
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system import forge, git
from audiagentic.foundation.time import now_iso_z

from . import merge_plan, publish
from .eligibility import ActiveWork

refuse_error = make_error_factory("CON", "WTMERGE", "project")

_BODY_LIMIT = 20000


def _body(repo: Path, body: str | None) -> str:
    """The pull request body: the caller's text, then the project's configured trailer (attribution lines)."""
    trailer = resolve_settings_cached(repo).get("worktrees.pr-trailer") or ""
    return "\n\n".join(part for part in ((body or "").strip(), str(trailer).strip()) if part)


def _own_open(found: tuple[forge.PullRequest, ...], branch: str) -> list[forge.PullRequest]:
    return [pr for pr in found if pr.state == "OPEN" and not pr.cross_repository and pr.head_branch == branch]


def merge(repo: Path, path: Path, *, title: str | None = None, body: str | None = None, head: str | None = None,
          active_work: ActiveWork, state_root: Path | None = None,
          find: Callable[[Path, str], tuple[forge.PullRequest, ...]] = forge.pull_requests_for_branch,
          identity: Callable[[Path], forge.RepositoryIdentity] = forge.repository_identity,
          push: Callable[..., dict[str, Any]] = publish.push,
          create: Callable[..., str] = forge.create_pull_request,
          retitle: Callable[..., None] = forge.set_pull_request_title,
          auto_merge: Callable[..., None] = forge.enable_auto_merge,
          read: Callable[..., forge.PullRequest] = forge.pull_request) -> dict[str, Any]:
    """Push the tip, open or reuse its pull request and request auto-merge; refuse on anything uncertain."""
    state = state_root or user_state_dir()
    plan = merge_plan.plan(repo, path, title=title, head=head, active_work=active_work, pull_requests=find,
                           identity=identity)
    codes = {b["code"] for b in plan["blockers"]}
    if codes == {"already-merged"}:  # a rerun after success: nothing to do, and that is not an error
        return {"worktree": str(path), "branch": plan["branch"], "tip": plan["tip"], "already-merged": True,
                "pushed": False, "created": False, "auto-merge": False, "pr": None, "url": None,
                "merge-state": "MERGED", "behind": False, "attempt": None}
    if plan["blockers"]:
        raise refuse_error(3, "This worktree cannot be published for merge: "
                           + "; ".join(f"{b['code']}: {b['detail']}" for b in plan["blockers"][:4]),
                           blockers=[b["code"] for b in plan["blockers"]])
    tip, branch, default, slug = plan["tip"], plan["branch"], plan["default-branch"], plan["repository"]
    new_body = _body(repo, body)
    if len(new_body) > _BODY_LIMIT or "\0" in new_body:
        raise refuse_error(3, f"The pull request body is longer than {_BODY_LIMIT} characters or contains a NUL byte")
    attempt = uuid.uuid4().hex
    receipt: dict[str, Any] = {"attempt": attempt, "kind": "merge", "worktree": str(path), "branch": branch,
                               "tip": tip, "repository": slug, "planned-pr": plan["pr"], "started": now_iso_z()}
    publish._receipt(state, repo, path, attempt, receipt, "STARTED")

    pushed = False
    if git.remote_branch_commit(path, "origin", branch) != tip:  # asks the remote itself, not a tracking ref
        push(repo, path, head=tip[:12], active_work=active_work, identity=identity, state_root=state)
        pushed = True
    receipt["pushed"] = pushed
    publish._receipt(state, repo, path, attempt, receipt, "PUSHED")

    existing = _own_open(find(repo, branch), branch)
    if len(existing) > 1 or (existing and plan["pr"] is not None and existing[0].number != plan["pr"]):
        raise refuse_error(4, "The open pull requests for this branch are not the one that was planned; resolve that first",
                           numbers=[pr.number for pr in existing])
    created = False
    if existing:
        pr = existing[0]
        if pr.base != default or pr.is_draft:  # validated before anything is changed on it
            raise refuse_error(5, f"Pull request #{pr.number} is a draft or does not target {default}; nothing was changed",
                               number=pr.number)
        if title is not None and pr.title != title:
            publish._receipt(state, repo, path, attempt, receipt, "RETITLE_INTENT")
            retitle(repo, pr.number, title, repository=slug)
    else:
        publish._receipt(state, repo, path, attempt, receipt, "CREATE_INTENT")
        receipt["url"] = create(repo, head=branch, base=default, title=title or "", body=new_body, repository=slug)
        created = True
        publish._receipt(state, repo, path, attempt, receipt, "PR_CREATED")
        found = _own_open(find(repo, branch), branch)
        if len(found) != 1:
            raise refuse_error(4, "The pull request was created but cannot be identified; check the forge before "
                                  "running this again (a rerun reuses it)", found=len(found), url=receipt["url"])
        pr = found[0]
    pr = read(repo, pr.number, repository=slug)
    receipt.update({"pr": pr.number, "created": created, "observed-head": pr.head_sha})
    publish._receipt(state, repo, path, attempt, receipt, "PR_READY")
    if pr.head_sha != tip or pr.base != default or pr.is_draft or pr.state != "OPEN" or pr.cross_repository:
        raise refuse_error(5, f"Pull request #{pr.number} does not match what was pushed (head {(pr.head_sha or '?')[:12]}, "
                              f"expected {tip[:12]}; base {pr.base}; {pr.state}); auto-merge was not requested",
                           number=pr.number)
    if not pr.auto_merge:
        publish._receipt(state, repo, path, attempt, receipt, "AUTO_MERGE_INTENT")
        auto_merge(repo, pr.number, head_sha=tip, repository=slug)  # the forge refuses if the branch moved
        pr = read(repo, pr.number, repository=slug)
        if not pr.auto_merge and pr.state != "MERGED":
            raise refuse_error(6, f"The forge did not accept auto-merge for #{pr.number}; check that auto-merge is "
                                  "allowed on the repository and that you may enable it", number=pr.number)
    publish._receipt(state, repo, path, attempt, receipt, "AUTO_MERGE_REQUESTED")
    return {"worktree": str(path), "branch": branch, "tip": tip, "pushed": pushed, "pr": pr.number, "url": pr.url,
            "created": created, "auto-merge": pr.auto_merge, "merged-now": pr.state == "MERGED",
            "merge-state": pr.merge_state, "behind": pr.merge_state == "BEHIND", "attempt": attempt}
