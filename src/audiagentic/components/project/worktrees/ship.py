"""One idempotent command from a finished task to a merged pull request (DW01 ``worktree ship``).

``ship`` is only orchestration of the reviewed steps, in the order a person would run them:

1. a tip a merged pull request already contains is reported as done (nothing is touched);
2. ``sync`` brings the branch up to date locally (a branch the default branch moved past would sit
   BEHIND and never merge under strict required checks);
3. ``merge`` pushes exactly the tip, opens or reuses the pull request and requests auto-merge.

It never waits for CI and never force-pushes. Every step converges, so running it again after a
release or other merge moved the default branch advances the same pull request: that rerun is the
whole "keep it up to date until it lands" procedure. Each step keeps its own refusals (dirty tree,
unfinished gateway work, a conflict, a diverged remote); ``ship`` adds none and loosens none.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.system import forge, git

from . import merge as merger
from . import sync as syncer
from .eligibility import ActiveWork


def _landed(repo: Path, branch: str, tip: str,
            find: Callable[[Path, str], tuple[forge.PullRequest, ...]]) -> forge.PullRequest | None:
    """A merged pull request of this branch that contains the tip, or ``None``."""
    try:
        found = find(repo, branch)
    except Exception:  # noqa: BLE001 - not knowing is not "merged"; the later steps ask the forge again
        return None
    for pr in found:
        if pr.state == "MERGED" and not pr.cross_repository and pr.head_branch == branch:
            if pr.head_sha == tip or git.is_ancestor(repo, tip, pr.head_sha):
                return pr
    return None


def ship(repo: Path, path: Path, *, title: str | None = None, body: str | None = None, head: str | None = None,
         active_work: ActiveWork, state_root: Path | None = None,
         find: Callable[[Path, str], tuple[forge.PullRequest, ...]] = forge.pull_requests_for_branch,
         sync: Callable[..., dict[str, Any]] = syncer.sync,
         merge: Callable[..., dict[str, Any]] = merger.merge) -> dict[str, Any]:
    """Sync, publish and request merge for ``path``; report where the pull request stands."""
    entry = next((e for e in git.list_worktrees(repo) if e.path == path), None)
    tip, branch = (entry.head, entry.branch) if entry is not None else (None, None)
    if tip and branch and (landed := _landed(repo, branch, tip, find)) is not None:
        return {"state": "merged", "worktree": str(path), "branch": branch, "tip": tip, "pr": landed.number,
                "url": landed.url, "synced": [], "pushed": False,
                "next": f"audiagentic worktree finish {path}"}
    synced = sync(repo, path, head=head, active_work=active_work, state_root=state_root)
    published = merge(repo, path, title=title, body=body, head=None, active_work=active_work, state_root=state_root)
    if published.get("already-merged") or published.get("merged-now"):
        state, nxt = "merged", f"audiagentic worktree finish {path}"
    elif published["behind"]:
        state, nxt = "behind", "run `audiagentic worktree ship` again (the default branch moved while the checks ran)"
    else:
        state, nxt = "queued", "auto-merge is on; run `audiagentic worktree ship` again if the default branch moves"
    return {"state": state, "worktree": str(path), "branch": published["branch"], "tip": published["tip"],
            "pr": published.get("pr"), "url": published.get("url"), "synced": synced["actions"],
            "pushed": published["pushed"], "created": published.get("created", False),
            "merge-state": published.get("merge-state"), "next": nxt}
