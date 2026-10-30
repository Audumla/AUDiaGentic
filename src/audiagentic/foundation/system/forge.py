"""Read-only pull-request and repository facts from the code forge (DW01).

GitHub through the ``gh`` CLI, the only forge supported so far. The module only
reads: it never merges, closes or comments. A fact the forge cannot give is an
error, never a guess, so callers treat "could not ask" as unknown and refuse.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory

forge_error = make_error_factory("EXT", "FORGE", "foundation")

_TIMEOUT_SECONDS = 60.0
_LIMIT = 100
_FIELDS = ("number,state,baseRefName,headRefName,headRefOid,mergeCommit,isCrossRepository,url,"
           "isDraft,autoMergeRequest,mergeStateStatus")


@dataclass(frozen=True)
class PullRequest:
    number: int
    state: str  # OPEN, CLOSED or MERGED
    base: str
    head_branch: str
    head_sha: str
    merge_commit: str | None
    cross_repository: bool
    url: str
    is_draft: bool = False
    auto_merge: bool = False
    merge_state: str | None = None  # GitHub's mergeStateStatus, e.g. CLEAN, BEHIND, BLOCKED


@dataclass(frozen=True)
class RepositoryIdentity:
    name_with_owner: str  # owner/name as the forge knows it
    default_branch: str
    can_push: bool


def _gh(repo: Path, *arguments: str) -> str:
    """Run one read-only ``gh`` command in ``repo`` and return stdout; typed errors, never a guess."""
    executable = shutil.which("gh")
    if executable is None:
        raise forge_error(1, "gh is not installed or not on PATH")
    try:
        done = subprocess.run([executable, *arguments], cwd=repo, capture_output=True, text=True,
                              timeout=_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise forge_error(3, "gh timed out", seconds=_TIMEOUT_SECONDS) from None
    except OSError as error:
        raise forge_error(1, "gh could not be started", reason=type(error).__name__) from None
    if done.returncode != 0:
        raise forge_error(2, "gh could not read from the forge", returncode=done.returncode,
                          stderr=done.stderr.strip()[-300:])
    return done.stdout


def repository_identity(repo: Path) -> RepositoryIdentity:
    """Which repository the forge says ``repo`` is, its default branch and whether the user may push."""
    try:
        row = json.loads(_gh(repo, "repo", "view", "--json", "nameWithOwner,defaultBranchRef,viewerPermission"))
        return RepositoryIdentity(
            name_with_owner=str(row["nameWithOwner"]), default_branch=str(row["defaultBranchRef"]["name"]),
            can_push=str(row["viewerPermission"]) in {"ADMIN", "MAINTAIN", "WRITE"})
    except (ValueError, KeyError, TypeError):
        raise forge_error(4, "gh returned a repository description this code cannot read") from None


def pull_requests_for_branch(repo: Path, branch: str) -> tuple[PullRequest, ...]:
    """Every pull request, in any state, whose head branch is ``branch`` on this repository."""
    stdout = _gh(repo, "pr", "list", "--head", branch, "--state", "all", "--limit", str(_LIMIT), "--json", _FIELDS)
    try:
        rows = json.loads(stdout or "[]")
        if len(rows) >= _LIMIT:
            # A full page may be cut short; an incomplete listing is no proof of anything.
            raise forge_error(5, "pull request listing may be incomplete", limit=_LIMIT)
        return tuple(
            PullRequest(
                number=int(row["number"]), state=str(row["state"]), base=str(row["baseRefName"]),
                head_branch=str(row["headRefName"]), head_sha=str(row["headRefOid"]),
                merge_commit=(row.get("mergeCommit") or {}).get("oid"),
                cross_repository=bool(row.get("isCrossRepository")), url=str(row.get("url", "")),
                is_draft=bool(row.get("isDraft")), auto_merge=row.get("autoMergeRequest") is not None,
                merge_state=row.get("mergeStateStatus"),
            )
            for row in rows
        )
    except (ValueError, KeyError, TypeError):
        raise forge_error(4, "gh returned a pull request listing this code cannot read") from None
