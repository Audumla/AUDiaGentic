"""Publishing a worktree's tip: user-defined checks, then one commit-bound non-force push (DW01 slice 4b).

Everything is bound to one full commit id. The preconditions (clean tree, the repository
the forge reports, push permission, no unfinished gateway work) are evaluated for that
commit, the configured checks run against it, the preconditions are evaluated again, and
only then is exactly that commit pushed as ``refs/heads/<branch>``, never forced. The
remote is read back afterwards and a receipt is written for each step.

The checks are trusted local code and are therefore defined only in the user's own
settings (``worktrees.checks``: id to a fixed argv, no shell); the project names which
ids must pass (``worktrees.pre-push``). A project file that defines or changes the
commands is refused: it is repository-controlled and would run on the user's machine.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.config.settings import resolve_settings_cached
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system import forge, git
from audiagentic.foundation.time import now_iso_z

from . import merge_plan, records
from .eligibility import ActiveWork

refuse_error = make_error_factory("CON", "WTPUSH", "project")

CHECK_TIMEOUT_SECONDS = 300.0
_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "SYSTEMROOT")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def configured_checks(repo: Path) -> list[tuple[str, list[str]]]:
    """The ordered ``(id, argv)`` the project requires, with commands taken from the user's settings only."""
    merged = resolve_settings_cached(repo)
    machine = resolve_settings_cached(machine_only=True)
    # The user's own list is always required: a project may add checks but cannot drop or replace them.
    names = list(dict.fromkeys([*(machine.get("worktrees.pre-push") or []), *(merged.get("worktrees.pre-push") or [])]))
    definitions = machine.get("worktrees.checks") or {}
    for name in names:
        argv = definitions.get(name)
        if argv is not None and (not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv)):
            raise refuse_error(2, f"worktrees.checks.{name} is not a non-empty list of strings")
    if (merged.get("worktrees.checks") or {}) != definitions:
        raise refuse_error(2, "worktrees.checks is defined or changed in the project settings; commands are honoured "
                              "only from your user settings")
    missing = [name for name in names if name not in definitions]
    if missing:
        raise refuse_error(3, f"The project requires the pre-push check(s) {', '.join(missing)}, which your user "
                              "settings do not define under worktrees.checks", missing=missing)
    return [(name, list(definitions[name])) for name in names]


def run_check(name: str, argv: list[str], *, worktree: Path, tip: str, base: str,
              runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> CheckResult:
    """Run one check with a fixed argv and a minimal environment; success is exit status 0."""
    values = {"{tip}": tip, "{base}": base, "{worktree}": str(worktree)}
    command = []
    for argument in argv:
        for token, value in values.items():
            argument = argument.replace(token, value)
        command.append(argument)
    executable = shutil.which(command[0])
    if executable is None:
        return CheckResult(name, False, f"executable {command[0]!r} was not found")
    environment = {key: os.environ[key] for key in _ENV_KEEP if key in os.environ}
    try:
        done = runner([executable, *command[1:]], cwd=worktree, env=environment, capture_output=True, text=True,
                      timeout=CHECK_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return CheckResult(name, False, f"timed out after {int(CHECK_TIMEOUT_SECONDS)} s")
    except OSError as error:
        return CheckResult(name, False, f"could not be started ({type(error).__name__})")
    tail = ((done.stdout or "") + (done.stderr or "")).strip()[-600:]
    return CheckResult(name, done.returncode == 0, "passed" if done.returncode == 0 else f"exit {done.returncode}: {tail}")


def _receipt(state: Path, repo: Path, path: Path, attempt: str, body: dict[str, Any], phase: str) -> None:
    body["phase"] = phase
    body.setdefault("phases", {})[phase] = now_iso_z()
    file = state / "worktrees" / "receipts" / records.repo_id(repo) / f"{attempt}.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(file, body)


def push(repo: Path, path: Path, *, head: str | None = None, active_work: ActiveWork, dry_run: bool = False,
         identity: Callable[[Path], forge.RepositoryIdentity] = forge.repository_identity,
         run: Callable[..., CheckResult] = run_check, state_root: Path | None = None) -> dict[str, Any]:
    """Run the configured checks against the tip and push exactly that commit, or refuse and change nothing."""
    state = state_root or user_state_dir()
    found = merge_plan.preconditions(repo, path, head=head, active_work=active_work, identity=identity)
    tip, entry = found.tip, found.entry
    blockers = list(found.blockers)
    if blockers:
        raise refuse_error(1, "This worktree cannot be pushed: " + "; ".join(f"{b.code}: {b.detail}" for b in blockers[:4]),
                           blockers=[b.code for b in blockers])
    checks = configured_checks(repo)
    try:
        base_commit = git.run_git(path, "merge-base", tip, found.base or "").strip()
    except Exception as error:
        raise refuse_error(1, "The commit range to publish cannot be established (no merge base with the remote "
                              "default branch); refusing without it") from error
    plan = {"worktree": str(path), "branch": entry.branch, "tip": tip, "base": base_commit,
            "checks": [name for name, _ in checks], "repository": found.who.name_with_owner if found.who else None}
    if dry_run:
        return {**plan, "dry-run": True, "pushed": False,
                "would": f"run {len(checks)} check(s), then git push origin {tip[:12]}:refs/heads/{entry.branch}"}

    if not entry.branch or not git.valid_branch_name(repo, entry.branch):
        raise refuse_error(1, "The branch name is not one git accepts; refusing to push it")
    attempt = uuid.uuid4().hex
    receipt: dict[str, Any] = {"attempt": attempt, **plan, "started": now_iso_z()}
    _receipt(state, repo, path, attempt, receipt, "STARTED")
    for name, argv in checks:
        result = run(name, argv, worktree=path, tip=tip, base=base_commit)
        receipt.setdefault("check-results", {})[name] = {"ok": result.ok}
        if not result.ok:
            _receipt(state, repo, path, attempt, receipt, "CHECK_FAILED")
            raise refuse_error(4, f"Pre-push check {name} failed: {result.detail}", check=name)
    _receipt(state, repo, path, attempt, receipt, "CHECKED")

    again = merge_plan.preconditions(repo, path, head=head, active_work=active_work, identity=identity)
    try:
        base_again = git.run_git(path, "merge-base", again.tip, again.base or "").strip()
    except Exception:  # noqa: BLE001 - an unreadable base is a changed plan
        base_again = ""
    if (again.blockers or again.tip != tip or again.entry.branch != entry.branch or base_again != base_commit
            or [name for name, _ in configured_checks(repo)] != plan["checks"]):
        _receipt(state, repo, path, attempt, receipt, "RECHECK_FAILED")
        raise refuse_error(5, "The worktree changed while the checks ran; nothing was pushed",
                           before=tip[:12], after=again.tip[:12], blockers=[b.code for b in again.blockers])
    _receipt(state, repo, path, attempt, receipt, "PUSH_ATTEMPTED")  # an ambiguous outcome is never retried blindly
    try:
        git.push_commit(path, "origin", tip, entry.branch or "")
    except Exception as error:
        _receipt(state, repo, path, attempt, receipt, "PUSH_FAILED")
        raise refuse_error(6, "git refused the push (it is never forced); fetch and reconcile the branch first",
                           reason=getattr(error, "details", None)) from error
    _receipt(state, repo, path, attempt, receipt, "PUSHED")
    try:
        remote = git.remote_branch_commit(path, "origin", entry.branch or "")
    except Exception as error:
        _receipt(state, repo, path, attempt, receipt, "UNCONFIRMED")
        raise refuse_error(7, "The push was sent but the remote could not be read back; check the branch on the forge "
                              "before pushing again", attempt=attempt) from error
    receipt["remote-commit"] = remote
    if remote != tip:
        _receipt(state, repo, path, attempt, receipt, "UNCONFIRMED")
        raise refuse_error(7, "The push finished but the remote does not report the pushed commit", remote=remote)
    _receipt(state, repo, path, attempt, receipt, "VERIFIED")
    return {**plan, "dry-run": False, "pushed": True, "remote-commit": remote, "attempt": attempt}
