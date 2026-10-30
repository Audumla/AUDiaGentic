"""Creating a task worktree (DW01 ``worktree start``).

One locked sequence: validate the names, fetch the remote default branch (a
stale base is refused, never used), refuse anything that already exists, create
branch and worktree in a single git operation, record the owner centrally, and
roll everything back if any later step fails. Nothing is written into the new
worktree.
"""
from __future__ import annotations

import getpass
import os
import re
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.config.settings import resolve_settings_cached
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system import git
from audiagentic.foundation.system.advisory_lock import AdvisoryLock
from audiagentic.foundation.time import now_iso_z

from . import records

invalid_error = make_error_factory("VAL", "WTSTART", "project")
conflict_error = make_error_factory("CON", "WTSTART", "project")

_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
_DEFAULT_PREFIX = "{owner}/"


@dataclass(frozen=True)
class StartedWorktree:
    worktree_id: str
    path: Path
    branch: str
    base: str
    base_head: str | None


def default_owner() -> dict[str, str]:
    """Who is starting: the Claude account directory name when present, else the OS user.

    Nothing here is configuration read from the environment: ``CLAUDE_CONFIG_DIR`` is the
    harness's own variable, and an explicit ``owner NAME`` on the command overrides it.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    return {"account": Path(config_dir).name if config_dir else getpass.getuser()}


def worktrees_root(repo: Path) -> Path:
    """Where new worktrees go: the ``worktrees.root`` setting, else ``<main worktree>.worktrees`` beside it."""
    main = git.list_worktrees(repo)[0].path
    configured = resolve_settings_cached(repo).get("worktrees.root")
    if configured:
        path = Path(configured).expanduser()
        return (path if path.is_absolute() else main.parent / path).resolve()
    return main.parent / f"{main.name}.worktrees"


def branch_name(repo: Path, slug: str, owner: dict[str, str]) -> str:
    prefix = resolve_settings_cached(repo).get("worktrees.branch-prefix", _DEFAULT_PREFIX)
    token = re.sub(r"[^a-z0-9-]+", "-", owner["account"].lower()).strip("-") or "agent"
    return f"{prefix.replace('{owner}', token)}{slug}"


def start(repo: Path, slug: str, *, plan_item: str | None = None, purpose: str = "",
          owner: dict[str, str] | None = None, state_root: Path | None = None) -> StartedWorktree:
    """Create a fresh task worktree from the remote default branch and record who owns it."""
    owner = {**default_owner(), **(owner or {})}
    if not _SLUG.fullmatch(slug):
        raise invalid_error(1, "A worktree slug is 1-48 lowercase letters, digits or hyphens, starting with a letter or digit",
                            slug=slug)
    if not all(_OWNER.fullmatch(value) for key, value in owner.items() if key == "account"):
        raise invalid_error(1, "The owner account name is not usable in a branch name", account=owner["account"])
    if plan_item is not None and not re.fullmatch(r"[A-Z]+\d+", plan_item):
        raise invalid_error(1, "A plan item id looks like DW01", plan_item=plan_item)
    branch = branch_name(repo, slug, owner)
    if not git.valid_branch_name(repo, branch):
        raise invalid_error(2, "git does not accept this branch name", branch=branch)

    main = git.list_worktrees(repo)[0].path
    base = git.default_branch(main)
    if base is None:
        raise invalid_error(3, "The remote default branch is unknown (no origin/HEAD, origin/main or origin/master)")
    remote, _, base_branch = base.partition("/")
    path = worktrees_root(repo) / slug

    state = state_root or user_state_dir()
    lock = state / "worktrees" / f"{records.repo_id(repo)}.start.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with AdvisoryLock(lock, timeout=60.0):
        if git.branch_exists(repo, branch):
            raise conflict_error(1, "That branch already exists", branch=branch)
        if path.exists() or any(entry.path == path for entry in git.list_worktrees(repo)):
            raise conflict_error(2, "That worktree path is already in use", path=str(path))
        try:
            git.fetch(main, remote, base_branch)
        except Exception as error:
            raise invalid_error(4, "Could not fetch the remote default branch; refusing to start from a stale base",
                                base=base) from error
        head = git.resolve_commit(main, base)
        record = records.WorktreeRecord(
            worktree_id=records.new_worktree_id(), path=str(path), branch=branch, owner=owner,
            created_at=now_iso_z(), purpose=purpose, plan_item=plan_item)
        path.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            git.add_worktree(main, path, branch, base)
            created = True
            records.register(repo, record, state_root=state_root)
        except BaseException:
            _roll_back(main, path, branch, created, record.worktree_id, repo, state_root)
            raise
    return StartedWorktree(record.worktree_id, path.resolve(), branch, base, head)


def _roll_back(main: Path, path: Path, branch: str, created: bool, worktree_id: str, repo: Path,
               state_root: Path | None) -> None:
    """Undo a half-finished start. Best effort, each step independent; never forces."""
    records.forget(repo, worktree_id, state_root=state_root)
    if created:
        try:
            git.remove_clean_worktree(main, path)
        except Exception:  # noqa: BLE001 - a leftover is reported by `list`/doctor, not hidden
            return
    if git.branch_exists(main, branch):
        try:
            git.delete_unmerged_branch(main, branch)
        except Exception:  # noqa: BLE001
            pass
