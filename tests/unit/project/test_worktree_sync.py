"""DW01 `worktree sync`: bring a branch up to date locally, never rewriting or guessing."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.project.worktrees import sync
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import git

IDLE = lambda _path: {"requests": [], "sessions": []}  # noqa: E731


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xstate"))
    for key, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"),
                       ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.invalid")):
        monkeypatch.setenv(key, value)  # the code under test runs git merge, which needs an identity
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    main = tmp_path / "main"
    _git(tmp_path, "clone", "-q", str(bare), str(main))
    _git(main, "checkout", "-q", "-b", "main")
    (main / "a.txt").write_text("one\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "one")
    _git(main, "push", "-q", "-u", "origin", "main")
    _git(main, "remote", "set-head", "origin", "main")
    feature = (tmp_path / "feature").resolve()
    _git(main, "worktree", "add", "-q", "-b", "me/feature", str(feature), "origin/main")
    (feature / "f.txt").write_text("f\n")
    _git(feature, "add", "f.txt")
    _git(feature, "commit", "-q", "-m", "feature")
    return {"repo": main.resolve(), "feature": feature, "bare": bare, "tmp": tmp_path}


def _advance_main(world, name="m.txt", text="m\n") -> str:
    other = world["tmp"] / f"adv-{name}"
    _git(world["tmp"], "clone", "-q", str(world["bare"]), str(other))
    (other / name).write_text(text)
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", f"main moves: {name}")
    _git(other, "push", "-q", "origin", "main")
    return _git(other, "rev-parse", "HEAD")


def _sync(world, **kwargs):
    return sync.sync(world["repo"], world["feature"], active_work=IDLE, **kwargs)


def test_a_branch_behind_the_default_branch_gets_a_merge_commit_not_a_rewrite(world) -> None:
    before = _git(world["feature"], "rev-parse", "HEAD")
    moved = _advance_main(world)
    result = _sync(world)
    after = _git(world["feature"], "rev-parse", "HEAD")
    assert result["changed"] is True and result["before"] == before and result["after"] == after != before
    assert _git(world["feature"], "rev-list", "--parents", "-n", "1", "HEAD").split()[1:] == [before, moved]
    assert (world["feature"] / "m.txt").exists() and (world["feature"] / "f.txt").exists()
    assert _git(world["feature"], "status", "--porcelain") == ""


def test_up_to_date_changes_nothing(world) -> None:
    result = _sync(world)
    assert result["actions"] == [] and result["changed"] is False and result["next"] is None


def test_dry_run_fetches_and_changes_nothing(world) -> None:
    _advance_main(world)
    before = _git(world["feature"], "rev-parse", "HEAD")
    result = _sync(world, dry_run=True)
    # nothing fetched, so the stale local view still says up to date, and the tree is untouched
    assert result["dry-run"] is True and _git(world["feature"], "rev-parse", "HEAD") == before
    assert git.resolve_commit(world["repo"], "origin/main") != _git(world["bare"], "rev-parse", "main")


def test_remote_branch_ahead_is_fast_forwarded_after_the_forge_updated_it(world) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    other = world["tmp"] / "forge-side"
    _git(world["tmp"], "clone", "-q", "-b", "me/feature", str(world["bare"]), str(other))
    (other / "ff.txt").write_text("ff\n")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "forge update")
    _git(other, "push", "-q", "origin", "me/feature")
    remote = _git(other, "rev-parse", "HEAD")
    result = _sync(world)
    assert _git(world["feature"], "rev-parse", "HEAD") == remote and any("fast-forward" in a for a in result["actions"])


def test_a_diverged_remote_branch_is_never_resolved(world) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    other = world["tmp"] / "forge-side"
    _git(world["tmp"], "clone", "-q", "-b", "me/feature", str(world["bare"]), str(other))
    (other / "theirs.txt").write_text("t\n")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "theirs")
    _git(other, "push", "-q", "origin", "me/feature")
    (world["feature"] / "mine.txt").write_text("m\n")
    _git(world["feature"], "add", ".")
    _git(world["feature"], "commit", "-q", "-m", "mine")
    mine = _git(world["feature"], "rev-parse", "HEAD")
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world)
    assert raised.value.code == "CON-WTSYNC-002" and _git(world["feature"], "rev-parse", "HEAD") == mine


def test_a_conflict_is_aborted_and_leaves_the_worktree_exactly_as_it_was(world) -> None:
    (world["feature"] / "a.txt").write_text("feature edit\n")
    _git(world["feature"], "commit", "-q", "-am", "edit a")
    before = _git(world["feature"], "rev-parse", "HEAD")
    _advance_main(world, name="a.txt", text="main edit\n")
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world)
    assert raised.value.code == "CON-WTSYNC-003" and "a.txt" in raised.value.message
    assert _git(world["feature"], "rev-parse", "HEAD") == before
    assert _git(world["feature"], "status", "--porcelain") == "" and not git.merge_in_progress(world["feature"])


def test_blockers_refuse_before_anything_is_fetched_or_changed(world) -> None:
    (world["feature"] / "dirty.txt").write_text("x")
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world)
    assert raised.value.code == "CON-WTSYNC-001" and "uncommitted-changes" in raised.value.message
    (world["feature"] / "dirty.txt").unlink()
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world, head="0" * 12)
    assert "head-mismatch" in raised.value.message
    with pytest.raises(AudiaGenticError) as raised:
        sync.sync(world["repo"], world["feature"], active_work=lambda _p: {"requests": ["r"], "sessions": []})
    assert "gateway-active-work" in raised.value.message
    with pytest.raises(AudiaGenticError) as raised:
        sync.sync(world["repo"], world["repo"], active_work=IDLE)
    assert raised.value.code == "CON-WTSYNC-001"


def test_sync_never_pushes(world) -> None:
    _advance_main(world)
    _sync(world)
    assert "refs/heads/me/feature" not in _git(world["bare"], "for-each-ref")  # the branch was never sent anywhere


def test_other_half_done_operations_also_block(world) -> None:
    git_dir = Path(_git(world["feature"], "rev-parse", "--absolute-git-dir"))
    (git_dir / "CHERRY_PICK_HEAD").write_text(_git(world["feature"], "rev-parse", "HEAD") + "\n")
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world)
    assert raised.value.code == "CON-WTSYNC-001" and "cherry-pick-in-progress" in raised.value.message


def test_repository_hooks_do_not_run_during_the_merge(world) -> None:
    _advance_main(world)
    marker = world["tmp"] / "hook-ran"
    hook = world["repo"] / ".git" / "hooks" / "post-merge"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    _sync(world)
    assert not marker.exists()


def test_a_branch_the_remote_has_but_that_cannot_be_fetched_stops_everything(world, monkeypatch) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    _advance_main(world)
    before = _git(world["feature"], "rev-parse", "HEAD")
    real_fetch = git.fetch

    def failing(repo, remote, branch, **kwargs):
        if branch == "me/feature":
            raise RuntimeError("network down")
        return real_fetch(repo, remote, branch, **kwargs)

    monkeypatch.setattr(sync.git, "fetch", failing)
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world)
    assert raised.value.code == "CON-WTSYNC-005" and _git(world["feature"], "rev-parse", "HEAD") == before


def test_an_ancestry_question_git_cannot_answer_changes_nothing(world, monkeypatch) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    other = world["tmp"] / "forge-side"
    _git(world["tmp"], "clone", "-q", "-b", "me/feature", str(world["bare"]), str(other))
    (other / "ff.txt").write_text("ff\n")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "forge update")
    _git(other, "push", "-q", "origin", "me/feature")
    before = _git(world["feature"], "rev-parse", "HEAD")
    monkeypatch.setattr(sync.git, "is_ancestor", lambda *a, **k: None)
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world)
    assert raised.value.code == "CON-WTSYNC-005" and _git(world["feature"], "rev-parse", "HEAD") == before


def test_a_failed_merge_after_a_fast_forward_says_so(world) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    other = world["tmp"] / "forge-side"
    _git(world["tmp"], "clone", "-q", "-b", "me/feature", str(world["bare"]), str(other))
    (other / "a.txt").write_text("forge edit\n")
    _git(other, "commit", "-q", "-am", "forge edits a")
    _git(other, "push", "-q", "origin", "me/feature")
    forged = _git(other, "rev-parse", "HEAD")
    _advance_main(world, name="a.txt", text="main edit\n")
    with pytest.raises(AudiaGenticError) as raised:
        _sync(world)
    assert raised.value.code == "CON-WTSYNC-003" and "fast-forward" in raised.value.message
    assert _git(world["feature"], "rev-parse", "HEAD") == forged and _git(world["feature"], "status", "--porcelain") == ""
