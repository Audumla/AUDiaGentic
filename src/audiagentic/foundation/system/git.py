"""Read-only git queries for repository and worktree management (DW01).

One runner for the git facts worktree tooling needs. Every query is read-only:
nothing here creates, removes, fetches, pushes or rewrites. Failures are typed
errors, and a fact git cannot report is ``None``, never a guess.
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


def ahead_behind(path: Path, base: str) -> tuple[int, int] | None:
    """``(commits ahead of base, commits behind base)`` for HEAD, or ``None`` if base is unknown."""
    try:
        ahead, behind = run_git(path, "rev-list", "--left-right", "--count", f"HEAD...{base}").split()
    except Exception:  # noqa: BLE001 - unknown base ref
        return None
    return int(ahead), int(behind)
