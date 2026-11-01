"""DW01: ``worktree ship`` orders sync then merge, converges on rerun and adds no check of its own."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.project.worktrees import ship as shipper
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import forge

IDLE = lambda _path: {"requests": [], "sessions": []}  # noqa: E731


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def task(tmp_path: Path, monkeypatch) -> tuple[Path, Path, str]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    main = tmp_path / "main"
    _git(tmp_path, "clone", "-q", str(remote), str(main))
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
    return main.resolve(), feature, _git(feature, "rev-parse", "HEAD")


def _pr(tip: str, *, state: str = "MERGED", number: int = 5) -> forge.PullRequest:
    return forge.PullRequest(number, state, "main", "me/feature", tip, "m" * 40 if state == "MERGED" else None,
                             False, f"https://example.invalid/{number}")


class _Calls:
    def __init__(self, merge_result: dict | None = None, sync_actions: list[str] | None = None) -> None:
        self.order: list[str] = []
        self.merge_result = merge_result or {"branch": "me/feature", "tip": "t" * 40, "pushed": True, "pr": 5,
                                             "url": "u", "created": True, "merge-state": "CLEAN", "behind": False}
        self.sync_actions = sync_actions or []

    def sync(self, *_a, **_k):
        self.order.append("sync")
        return {"actions": self.sync_actions}

    def merge(self, *_a, **_k):
        self.order.append("merge")
        return self.merge_result


def _ship(repo, feature, calls, prs=()):
    return shipper.ship(repo, feature, active_work=IDLE, find=lambda _r, _b: tuple(prs), sync=calls.sync, merge=calls.merge)


def test_syncs_then_publishes_and_reports_queued(task) -> None:
    repo, feature, _tip = task
    calls = _Calls(sync_actions=["merge origin/main (2 commit(s) behind)"])
    result = _ship(repo, feature, calls)
    assert calls.order == ["sync", "merge"]
    assert result["state"] == "queued" and result["synced"] and result["pushed"] and result["pr"] == 5


def test_a_pull_request_behind_the_default_branch_asks_for_a_rerun(task) -> None:
    repo, feature, _tip = task
    calls = _Calls(merge_result={"branch": "me/feature", "tip": "t" * 40, "pushed": False, "pr": 5, "url": "u",
                                 "merge-state": "BEHIND", "behind": True})
    result = _ship(repo, feature, calls)
    assert result["state"] == "behind" and "again" in result["next"]


def test_a_tip_already_in_a_merged_pull_request_touches_nothing(task) -> None:
    repo, feature, tip = task
    calls = _Calls()
    result = _ship(repo, feature, calls, prs=[_pr(tip)])
    assert calls.order == [] and result["state"] == "merged" and result["next"].startswith("audiagentic worktree finish")


def test_a_merged_head_that_contains_the_tip_counts_as_landed(task) -> None:
    repo, feature, tip = task
    later = _git(feature, "commit-tree", f"{tip}^{{tree}}", "-p", tip, "-m", "later")
    calls = _Calls()
    assert _ship(repo, feature, calls, prs=[_pr(later)])["state"] == "merged" and calls.order == []


def test_an_open_pull_request_does_not_count_as_landed(task) -> None:
    repo, feature, tip = task
    calls = _Calls()
    _ship(repo, feature, calls, prs=[_pr(tip, state="OPEN")])
    assert calls.order == ["sync", "merge"]


def test_a_refusing_sync_stops_before_anything_is_published(task) -> None:
    repo, feature, _tip = task
    calls = _Calls()

    def refuse(*_a, **_k):
        calls.order.append("sync")
        raise AudiaGenticError("CON-WTSYNC-001", "validation", "conflict")

    with pytest.raises(AudiaGenticError):
        shipper.ship(repo, feature, active_work=IDLE, find=lambda _r, _b: (), sync=refuse, merge=calls.merge)
    assert calls.order == ["sync"]


def test_merged_now_is_reported_as_merged(task) -> None:
    repo, feature, _tip = task
    calls = _Calls(merge_result={"branch": "me/feature", "tip": "t" * 40, "pushed": True, "pr": 5, "url": "u",
                                 "merge-state": "MERGED", "behind": False, "merged-now": True})
    assert _ship(repo, feature, calls)["state"] == "merged"
