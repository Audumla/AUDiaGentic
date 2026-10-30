"""Read-only pull-request facts from the code forge (DW01).

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
_FIELDS = "number,state,baseRefName,headRefName,headRefOid,mergeCommit,isCrossRepository,url"


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


def pull_requests_for_branch(repo: Path, branch: str) -> tuple[PullRequest, ...]:
    """Every pull request, in any state, whose head branch is ``branch`` on this repository."""
    executable = shutil.which("gh")
    if executable is None:
        raise forge_error(1, "gh is not installed or not on PATH")
    try:
        done = subprocess.run(
            [executable, "pr", "list", "--head", branch, "--state", "all", "--limit", str(_LIMIT), "--json", _FIELDS],
            cwd=repo, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        raise forge_error(3, "gh timed out", seconds=_TIMEOUT_SECONDS) from None
    except OSError as error:
        raise forge_error(1, "gh could not be started", reason=type(error).__name__) from None
    if done.returncode != 0:
        raise forge_error(2, "gh could not list pull requests", returncode=done.returncode,
                          stderr=done.stderr.strip()[-300:])
    try:
        rows = json.loads(done.stdout or "[]")
        if len(rows) >= _LIMIT:
            # A full page may be cut short; an incomplete listing is no proof of anything.
            raise forge_error(5, "pull request listing may be incomplete", limit=_LIMIT)
        return tuple(
            PullRequest(
                number=int(row["number"]), state=str(row["state"]), base=str(row["baseRefName"]),
                head_branch=str(row["headRefName"]), head_sha=str(row["headRefOid"]),
                merge_commit=(row.get("mergeCommit") or {}).get("oid"),
                cross_repository=bool(row.get("isCrossRepository")), url=str(row.get("url", "")),
            )
            for row in rows
        )
    except (ValueError, KeyError, TypeError):
        raise forge_error(4, "gh returned a pull request listing this code cannot read") from None
