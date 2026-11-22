"""Pull-request and repository facts from the code forge, and three named writes (DW01).

GitHub through the ``gh`` CLI, the only forge supported so far. It reads, plus three
named writes at the end (open a pull request, set its title or body, request auto-merge); it
never merges, closes or comments itself. Pull requests are read and edited through the REST API
(``gh api``): ``gh pr view/list/edit`` query GraphQL fields (login, name, slug) that need the
``read:org`` scope, which the container's token does not have. A fact the forge cannot give is an
error, never a guess, so callers treat "could not ask" as unknown and refuse.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from audiagentic.foundation.contracts.errors import make_error_factory

forge_error = make_error_factory("EXT", "FORGE", "source-control")

_TIMEOUT_SECONDS = 60.0
_LIMIT = 100


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
    title: str = ""
    body: str = ""


@dataclass(frozen=True)
class RepositoryIdentity:
    name_with_owner: str  # owner/name as the forge knows it
    default_branch: str
    can_push: bool


def _gh(repo: Path, *arguments: str, stdin: str | None = None) -> str:
    """Run one ``gh`` command in ``repo`` and return stdout; typed errors, never a guess."""
    executable = shutil.which("gh")
    if executable is None:
        raise forge_error(1, "gh is not installed or not on PATH")
    try:
        done = subprocess.run([executable, *arguments], cwd=repo, capture_output=True, text=True, input=stdin,
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


def _pull_request(row: dict) -> PullRequest:
    """A pull request from a REST ``pulls`` object."""
    head, base = row["head"], row["base"]
    state = "MERGED" if row.get("merged_at") else str(row["state"]).upper()
    head_repo = (head.get("repo") or {}).get("full_name")
    return PullRequest(
        number=int(row["number"]), state=state, base=str(base["ref"]),
        head_branch=str(head["ref"]), head_sha=str(head["sha"]),
        merge_commit=row.get("merge_commit_sha") if state == "MERGED" else None,
        cross_repository=head_repo is None or head_repo != (base.get("repo") or {}).get("full_name"),
        url=str(row.get("html_url", "")), is_draft=bool(row.get("draft")),
        auto_merge=row.get("auto_merge") is not None,
        merge_state=(str(row["mergeable_state"]).upper() if row.get("mergeable_state") else None),
        title=str(row.get("title", "")), body=str(row.get("body") or ""),
    )


def _repo_path(repository: str | None) -> str:
    return f"repos/{repository}" if repository else "repos/{owner}/{repo}"


def pull_requests_for_branch(repo: Path, branch: str) -> tuple[PullRequest, ...]:
    """Every pull request, in any state, whose head branch is ``branch`` on this repository."""
    endpoint = f"repos/{{owner}}/{{repo}}/pulls?state=all&per_page={_LIMIT}&head={{owner}}:{quote(branch, safe='')}"
    stdout = _gh(repo, "api", endpoint)
    try:
        rows = json.loads(stdout or "[]")
        if len(rows) >= _LIMIT:
            # A full page may be cut short; an incomplete listing is no proof of anything.
            raise forge_error(5, "pull request listing may be incomplete", limit=_LIMIT)
        # The listing carries no merge state; an open request is read again for it.
        return tuple(_pull_request(row) if str(row.get("state")) != "open"
                     else pull_request(repo, int(row["number"])) for row in rows)
    except (ValueError, KeyError, TypeError):
        raise forge_error(4, "gh returned a pull request listing this code cannot read") from None


def pull_request(repo: Path, number: int, *, repository: str | None = None) -> PullRequest:
    """One pull request by number, read fresh; ``repository`` (owner/name) pins which repository it is read from."""
    try:
        return _pull_request(json.loads(_gh(repo, "api", f"{_repo_path(repository)}/pulls/{number}")))
    except (ValueError, KeyError, TypeError):
        raise forge_error(4, "gh returned a pull request this code cannot read") from None


# --- writes: the three named operations `worktree merge` needs; none merges or closes anything itself ---


def create_pull_request(repo: Path, *, head: str, base: str, title: str, body: str,
                        repository: str | None = None) -> str:
    """Open a pull request from branch ``head`` into ``base`` and return its URL.

    The body travels on stdin (no argument-length limit, no argument injection).
    """
    pin = ["--repo", repository] if repository else []
    output = _gh(repo, "pr", "create", *pin, "--head", head, "--base", base, "--title", title, "--body-file", "-",
                 stdin=body)
    return output.strip().splitlines()[-1] if output.strip() else ""


def set_pull_request_text(repo: Path, number: int, *, title: str | None = None, body: str | None = None,
                          repository: str | None = None) -> None:
    """Set the title and/or body through REST; the squash commit takes its subject from the title.

    Values are sent as raw fields (``--raw-field``), so a leading dash or ``@`` is never interpreted.
    """
    fields = [part for key, value in (("title", title), ("body", body)) if value is not None
              for part in ("--raw-field", f"{key}={value}")]
    if fields:
        _gh(repo, "api", "--method", "PATCH", f"{_repo_path(repository)}/pulls/{number}", *fields)


def enable_auto_merge(repo: Path, number: int, *, head_sha: str, repository: str | None = None) -> None:
    """Ask the forge to squash-merge the pull request once its required checks pass.

    ``head_sha`` is enforced by the forge (``--match-head-commit``): if the branch moved, auto-merge is
    not enabled. The forge may merge at once when nothing is required of the pull request, so the
    repository's rules, not this call, are what make it wait for checks.
    """
    pin = ["--repo", repository] if repository else []
    _gh(repo, "pr", "merge", str(number), *pin, "--auto", "--squash", "--match-head-commit", head_sha)
