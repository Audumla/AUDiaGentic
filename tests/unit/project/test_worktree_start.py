"""DW01 slice 2: `worktree start` creates, records and rolls back cleanly."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from audiagentic.commands import worktree as worktree_command
from audiagentic.components.project.worktrees import lifecycle, records
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import git

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **ENV}).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "accounts" / "Alice"))
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    main = tmp_path / "proj"
    _git(tmp_path, "clone", "-q", str(remote), str(main))
    _git(main, "checkout", "-q", "-b", "main")
    (main / "a.txt").write_text("one\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-q", "-m", "one")
    _git(main, "push", "-q", "-u", "origin", "main")
    _git(main, "remote", "set-head", "origin", "main")
    return main.resolve()


def _push_upstream_commit(repo: Path, tmp_path: Path) -> str:
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    (other / "b.txt").write_text("two\n")
    _git(other, "add", "b.txt")
    _git(other, "commit", "-q", "-m", "two")
    _git(other, "push", "-q", "origin", "main")
    return _git(other, "rev-parse", "HEAD")


def test_start_creates_branch_and_worktree_from_the_fresh_remote_head(repo: Path, tmp_path: Path) -> None:
    newest = _push_upstream_commit(repo, tmp_path)  # the local origin/main ref is now stale
    started = lifecycle.start(repo, "my-task", plan_item="DW01", purpose="try it")

    assert started.path == (repo.parent / "proj.worktrees" / "my-task").resolve()
    assert started.branch == "alice/my-task" and started.base == "origin/main"
    assert started.base_head == newest  # fetched first, so not the stale commit
    assert _git(started.path, "rev-parse", "HEAD") == newest
    assert _git(started.path, "branch", "--show-current") == "alice/my-task"
    # No upstream tracking (a plain `git push` must not target main), nothing written in the tree.
    assert subprocess.run(["git", "rev-parse", "--abbrev-ref", "alice/my-task@{upstream}"], cwd=repo,
                          capture_output=True).returncode != 0
    assert _git(started.path, "status", "--porcelain") == ""

    stored = records.read_records(repo)[started.worktree_id]
    assert (stored.branch, stored.plan_item, stored.purpose) == ("alice/my-task", "DW01", "try it")
    assert stored.owner["account"] == "Alice" and Path(stored.path) == started.path
    assert started.path in [entry.path for entry in git.list_worktrees(repo)]


@pytest.mark.parametrize("slug", ["", "Up", "-lead", "has space", "a/b", "x" * 49, "dot.dot"])
def test_invalid_slugs_are_refused_before_anything_is_created(repo: Path, slug: str) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        lifecycle.start(repo, slug)
    assert raised.value.code == "VAL-WTSTART-001"
    assert len(git.list_worktrees(repo)) == 1 and not (repo.parent / "proj.worktrees").exists()


def test_existing_branch_or_path_is_a_conflict_and_changes_nothing(repo: Path) -> None:
    first = lifecycle.start(repo, "task")
    with pytest.raises(AudiaGenticError) as raised:
        lifecycle.start(repo, "task")
    assert raised.value.code == "CON-WTSTART-001"

    _git(repo, "branch", "alice/other", "origin/main")
    with pytest.raises(AudiaGenticError) as raised:
        lifecycle.start(repo, "other")
    assert raised.value.code == "CON-WTSTART-001"

    squatter = repo.parent / "proj.worktrees" / "taken"
    squatter.mkdir(parents=True)
    with pytest.raises(AudiaGenticError) as raised:
        lifecycle.start(repo, "taken")
    assert raised.value.code == "CON-WTSTART-002"
    assert [entry.path for entry in git.list_worktrees(repo)] == [repo, first.path]


def test_unreachable_remote_refuses_instead_of_using_a_stale_base(repo: Path, tmp_path: Path) -> None:
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    with pytest.raises(AudiaGenticError) as raised:
        lifecycle.start(repo, "task")
    assert raised.value.code == "VAL-WTSTART-004"
    assert len(git.list_worktrees(repo)) == 1
    assert not git.branch_exists(repo, "alice/task") and records.read_records(repo) == {}


def test_a_failure_after_the_worktree_exists_rolls_everything_back(repo: Path, monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(records, "register", broken)
        with pytest.raises(RuntimeError):
            lifecycle.start(repo, "task")
    assert len(git.list_worktrees(repo)) == 1
    assert not git.branch_exists(repo, "alice/task")
    assert not (repo.parent / "proj.worktrees" / "task").exists()
    assert records.read_records(repo) == {}
    lifecycle.start(repo, "task")  # and the same slug works afterwards


def test_concurrent_starts_of_one_slug_have_exactly_one_winner(repo: Path) -> None:
    outcomes: list[object] = []

    def attempt() -> None:
        try:
            outcomes.append(lifecycle.start(repo, "race"))
        except AudiaGenticError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    winners = [item for item in outcomes if not isinstance(item, str)]
    assert len(winners) == 1 and sorted(item for item in outcomes if isinstance(item, str)) == ["CON-WTSTART-001"] * 3
    assert len(records.read_records(repo)) == 1 and len(git.list_worktrees(repo)) == 2


def test_command_prints_the_path_and_json(repo: Path, capsys) -> None:
    assert worktree_command.dispatch_keyword(
        ["start", "cli-task", "item", "DW01", "purpose", "from the cli", "project", str(repo), "output", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"].endswith("proj.worktrees/cli-task") and payload["branch"] == "alice/cli-task"
    assert Path(payload["path"]).is_dir()

    assert worktree_command.dispatch_keyword(["start", "Bad Slug", "project", str(repo)]) == 1
    for bad in (["start"], ["start", "x", "item"], ["start", "x", "frob", "y"], ["start", "x", "--force"],
                ["start", "x", "item", "DW01", "item", "DW02"]):
        assert worktree_command.dispatch_keyword(bad) == 2, bad
    capsys.readouterr()
    assert worktree_command.dispatch_keyword(["start", "help"]) == 0
    assert "worktree start" in capsys.readouterr().out
