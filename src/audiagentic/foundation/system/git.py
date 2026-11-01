"""Git queries and the few named mutators worktree management needs (DW01).

One runner for the git facts worktree tooling needs. Queries are read-only and
a fact git cannot report is ``None``, never a guess. The only mutators are the
small named functions at the end (fetch, add/remove worktree, delete a branch,
create a ref, and one non-force push of an exact commit); none rewrites history,
and each is used only by the worktree lifecycle, which owns its rollback. Failures are typed errors.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory

git_error = make_error_factory("EXT", "GIT", "foundation")

_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class WorktreeEntry:
    """One row of ``git worktree list``; the first row is the main worktree."""

    path: Path
    head: str | None
    branch: str | None  # None for a detached HEAD
    locked: bool
    prunable: bool
    bare: bool


def run_git(cwd: Path, *args: str, timeout: float = _TIMEOUT_SECONDS) -> str:
    """Run one git command in ``cwd`` and return stdout; never prompts or paginates."""
    executable = shutil.which("git")
    if executable is None:
        raise git_error(1, "git is not installed or not on PATH")
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "LC_ALL": "C"}
    try:
        done = subprocess.run(
            [executable, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
            check=False, env=environment,
        )
    except subprocess.TimeoutExpired:
        raise git_error(3, "git timed out", command=args[0] if args else "", seconds=timeout) from None
    except OSError as error:
        raise git_error(1, "git could not be started", reason=type(error).__name__) from None
    if done.returncode != 0:
        raise git_error(2, "git command failed", command=args[0] if args else "",
                        returncode=done.returncode, stderr=done.stderr.strip()[-300:])
    return done.stdout


def common_dir(repo: Path) -> Path:
    """The git common directory, shared by a repository and all its worktrees."""
    return Path(run_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).resolve()


def list_worktrees(repo: Path) -> tuple[WorktreeEntry, ...]:
    """Every worktree of the repository containing ``repo``, main worktree first."""
    entries: list[WorktreeEntry] = []
    for block in run_git(repo, "worktree", "list", "--porcelain", "-z").split("\0\0"):
        fields = [field for field in block.split("\0") if field]
        if not fields or not fields[0].startswith("worktree "):
            continue
        values = {field.split(" ", 1)[0]: (field.split(" ", 1) + [""])[1] for field in fields}
        branch = values.get("branch")
        entries.append(WorktreeEntry(
            path=Path(fields[0][len("worktree "):]).resolve(),
            head=values.get("HEAD") or None,
            branch=branch.removeprefix("refs/heads/") if branch else None,
            locked="locked" in values,
            prunable="prunable" in values,
            bare="bare" in values,
        ))
    return tuple(entries)


def default_branch(repo: Path, remote: str = "origin") -> str | None:
    """The remote's default branch as a ref such as ``origin/main``, from local refs only.

    Reads ``refs/remotes/<remote>/HEAD``; without it, the first of ``main`` and
    ``master`` that exists on the remote. ``None`` when neither is known.
    """
    try:
        return run_git(repo, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD").strip() or None
    except Exception:  # noqa: BLE001 - an unset remote HEAD is an ordinary state
        pass
    for name in ("main", "master"):
        try:
            run_git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{name}")
        except Exception:  # noqa: BLE001 - absent ref
            continue
        return f"{remote}/{name}"
    return None


def changes(path: Path) -> tuple[int, int]:
    """``(tracked changes, untracked files)`` of a worktree; ignored files are not counted."""
    tracked = untracked = 0
    for record in run_git(path, "status", "--porcelain=v1", "-z").split("\0"):
        if not record:
            continue
        if record.startswith("??"):
            untracked += 1
        elif record[:2] != "!!":
            tracked += 1
    return tracked, untracked


def resolve_commit(repo: Path, ref: str = "HEAD") -> str | None:
    """The commit ``ref`` points to, or ``None`` if git cannot resolve it."""
    try:
        return run_git(repo, "rev-parse", "--verify", "--quiet", ref).strip() or None
    except Exception:  # noqa: BLE001 - unknown ref
        return None


def ahead_behind(path: Path, base: str) -> tuple[int, int] | None:
    """``(commits ahead of base, commits behind base)`` for HEAD, or ``None`` if base is unknown."""
    try:
        ahead, behind = run_git(path, "rev-list", "--left-right", "--count", f"HEAD...{base}").split()
    except Exception:  # noqa: BLE001 - unknown base ref
        return None
    return int(ahead), int(behind)


def valid_branch_name(repo: Path, name: str) -> bool:
    """Whether git accepts ``name`` as a branch name (refs/heads rules)."""
    try:
        run_git(repo, "check-ref-format", "--branch", name)
    except Exception:  # noqa: BLE001 - any refusal means invalid
        return False
    return True


def branch_exists(repo: Path, name: str) -> bool:
    try:
        run_git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
    except Exception:  # noqa: BLE001 - absent ref
        return False
    return True


def remote_url(repo: Path, remote: str = "origin", *, push: bool = False) -> str | None:
    """The configured fetch (or push) URL of ``remote``; ``None`` when there is no such remote.

    Callers compare or parse it but never print it: URLs may carry credentials.
    """
    try:
        return run_git(repo, "remote", "get-url", *(["--push"] if push else []), remote).strip() or None
    except Exception:  # noqa: BLE001 - no such remote
        return None


def is_ancestor(repo: Path, commit: str, ref: str) -> bool | None:
    """Whether ``commit`` is reachable from ``ref``; ``None`` when either is unknown locally."""
    if resolve_commit(repo, f"{commit}^{{commit}}") is None or resolve_commit(repo, ref) is None:
        return None
    try:
        run_git(repo, "merge-base", "--is-ancestor", commit, ref)
    except Exception as error:  # noqa: BLE001 - only exit status 1 means "not an ancestor"
        return False if (getattr(error, "details", None) or {}).get("returncode") == 1 else None
    return True


def commits_not_in(repo: Path, tip: str, base: str) -> int | None:
    """Commits reachable from ``tip`` but not from ``base``; ``None`` when git cannot say."""
    try:
        return int(run_git(repo, "rev-list", "--count", f"{base}..{tip}").strip())
    except Exception:  # noqa: BLE001 - unknown ref
        return None


def ignored_entries(path: Path) -> list[str]:
    """Top-level ignored files and directories of a worktree, as git reports them."""
    entries = []
    for record in run_git(path, "status", "--porcelain=v1", "-z", "--ignored=traditional").split("\0"):
        if record.startswith("!! "):
            entries.append(record[3:])
    return sorted(entries)


def initialized_submodules(path: Path) -> list[str]:
    """Submodule paths that are checked out (``git submodule status`` does not start with ``-``)."""
    paths = []
    for line in run_git(path, "submodule", "status").splitlines():
        if line and not line.startswith("-"):
            paths.append(line[1:].split(" ", 2)[1])
    return paths


# --- mutators: used only by the worktree lifecycle, which owns the rollback ---


def fetch(repo: Path, remote: str, branch: str, *, timeout: float = 120.0) -> None:
    """Update ``<remote>/<branch>`` from the remote. Raises when it cannot."""
    run_git(repo, "fetch", "--quiet", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}",
            timeout=timeout)


def fetch_pull_head(repo: Path, remote: str, number: int, *, timeout: float = 120.0) -> None:
    """Fetch the objects of a pull request's head (``refs/pull/N/head``) without creating any ref."""
    run_git(repo, "fetch", "--quiet", remote, f"refs/pull/{int(number)}/head", timeout=timeout)


def add_worktree(repo: Path, path: Path, branch: str, base: str) -> None:
    """Create ``branch`` at ``base`` and check it out at ``path`` in one git operation (no tracking)."""
    run_git(repo, "worktree", "add", "--quiet", "--no-track", "-b", branch, str(path), base)


def remove_clean_worktree(repo: Path, path: Path) -> None:
    """Remove a worktree git considers clean. Never forces: a dirty tree is an error."""
    run_git(repo, "worktree", "remove", str(path))


def delete_unmerged_branch(repo: Path, branch: str) -> None:
    """Delete a local branch the caller just created and knows carries no commits of its own."""
    run_git(repo, "branch", "-D", branch)


def create_bundle(repo: Path, destination: Path, ref: str, exclude: str | None) -> None:
    """Write a git bundle of ``ref`` (without ``exclude``'s history when given); an empty bundle is an error."""
    arguments = ["bundle", "create", str(destination), ref]
    if exclude:
        arguments.append(f"^{exclude}")
    run_git(repo, *arguments, timeout=300.0)


def verify_bundle(repo: Path, bundle: Path) -> None:
    """Raise unless git can read the bundle and every prerequisite commit is present."""
    run_git(repo, "bundle", "verify", str(bundle), timeout=300.0)


def create_ref(repo: Path, ref: str, commit: str) -> None:
    """Create ``ref`` at ``commit``; an existing ref at the same commit is fine, anywhere else is an error."""
    existing = resolve_commit(repo, ref)
    if existing == commit:
        return
    run_git(repo, "update-ref", ref, commit, "0" * 40)  # the zero old-value makes this create-only


def delete_branch_at(repo: Path, branch: str, commit: str) -> None:
    """Delete the local branch only if it still points at ``commit`` (compare-and-swap, no force)."""
    run_git(repo, "update-ref", "-d", f"refs/heads/{branch}", commit)


def operation_in_progress(path: Path) -> str | None:
    """Name of a half-done git operation in this worktree (merge, cherry-pick, revert, rebase), or ``None``."""
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if resolve_commit(path, name) is not None:
            return name.removesuffix("_HEAD").replace("_", "-").lower()
    for name in ("rebase-merge", "rebase-apply"):
        if Path(run_git(path, "rev-parse", "--path-format=absolute", "--git-path", name).strip()).exists():
            return "rebase"
    return None


def merge_in_progress(path: Path) -> bool:
    """Whether a merge is half done in this worktree (``MERGE_HEAD`` exists)."""
    return resolve_commit(path, "MERGE_HEAD") is not None


def conflicted_paths(path: Path) -> list[str]:
    """Paths with unresolved merge conflicts."""
    return [name for name in run_git(path, "diff", "--name-only", "--diff-filter=U").splitlines() if name]


def merge_fast_forward(path: Path, ref: str) -> None:
    """Move the checked-out branch forward to ``ref``; an error if that is not a fast-forward."""
    run_git(path, "-c", "core.hooksPath=/dev/null", "merge", "--ff-only", "--quiet", ref)


def merge_ref(path: Path, ref: str) -> None:
    """Merge ``ref`` into the checked-out branch with a merge commit (never a rebase). Conflicts raise."""
    run_git(path, "-c", "core.hooksPath=/dev/null", "merge", "--no-edit", "--quiet", ref)


def merge_abort(path: Path) -> None:
    run_git(path, "merge", "--abort")


def remote_branch_commit(repo: Path, remote: str, branch: str) -> str | None:
    """The commit ``refs/heads/<branch>`` has on the remote right now (a network read), or ``None`` if absent.

    Strict: exactly one record for exactly that ref with a full-length hexadecimal id, else an error.
    """
    reference = f"refs/heads/{branch}"
    records = [line.split("\t") for line in run_git(repo, "ls-remote", remote, reference, timeout=120.0).splitlines()]
    matching = [record for record in records if len(record) == 2 and record[1] == reference]
    if len(matching) != len(records) or len(matching) > 1:
        raise git_error(5, "the remote returned records this code cannot read", branch=branch)
    if not matching:
        return None
    commit = matching[0][0]
    if len(commit) not in (40, 64) or any(character not in "0123456789abcdef" for character in commit):
        raise git_error(5, "the remote returned an object id this code cannot read", branch=branch)
    return commit


def push_commit(repo: Path, remote: str, commit: str, branch: str) -> None:
    """Publish exactly ``commit`` as ``refs/heads/<branch>`` on ``remote``. Never forces, never a branch name.

    Git refuses a push that is not a fast-forward of the remote branch; that refusal is an error here.
    """
    run_git(repo, "-c", "core.hooksPath=/dev/null", "-c", "push.followTags=false", "push", "--porcelain", "--no-verify",
            "--no-follow-tags", remote, f"{commit}:refs/heads/{branch}", timeout=180.0)
