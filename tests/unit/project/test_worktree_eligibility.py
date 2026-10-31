"""DW01 slice 3b: the read-only verdict on whether a worktree may be finished."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.project.worktrees import eligibility
from audiagentic.foundation.system import forge, git


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    main = tmp_path / "main"
    _git(tmp_path, "clone", "-q", str(remote), str(main))
    _git(main, "checkout", "-q", "-b", "main")
    (main / ".gitignore").write_text("*.log\n__pycache__/\n")
    (main / "a.txt").write_text("one\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "one")
    _git(main, "push", "-q", "-u", "origin", "main")
    _git(main, "remote", "set-head", "origin", "main")
    return main.resolve()


@pytest.fixture
def merged(repo: Path) -> tuple[Path, str, str]:
    """A feature worktree whose work was squash-merged onto origin/main: (path, tip, squash commit)."""
    feature = (repo.parent / "feature").resolve()
    _git(repo, "worktree", "add", "-q", "-b", "feature", str(feature), "origin/main")
    (feature / "f.txt").write_text("f\n")
    _git(feature, "add", "f.txt")
    _git(feature, "commit", "-q", "-m", "feature")
    tip = _git(feature, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("f\n")  # the squash: same content, different commit
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "squash")
    _git(repo, "push", "-q", "origin", "main")
    return feature, tip, _git(repo, "rev-parse", "HEAD")


def _pr(tip: str, merge: str | None, *, number: int = 7, state: str = "MERGED", base: str = "main",
        branch: str = "feature", cross: bool = False) -> forge.PullRequest:
    return forge.PullRequest(number, state, base, branch, tip, merge, cross, f"https://example.invalid/{number}")


def _verdict(repo: Path, feature: Path, prs, *, active=None) -> dict:
    result = eligibility.assess_all(
        repo, active_work=active or (lambda _path: {"requests": [], "sessions": []}),
        pull_requests=lambda _repo, _branch: tuple(prs) if not isinstance(prs, Exception) else (_ for _ in ()).throw(prs))
    return next(row for row in result["worktrees"] if row["path"] == str(feature))


def _codes(row: dict) -> set[str]:
    return {blocker["code"] for blocker in row["blockers"]}


def test_squash_merged_clean_worktree_is_eligible(repo, merged) -> None:
    feature, tip, squash = merged
    row = _verdict(repo, feature, [_pr(tip, squash)])
    assert row["verdict"] == "eligible" and row["blockers"] == [] and row["pr"] == 7


@pytest.mark.parametrize("prs, code, unknown", [
    ([], "unmerged", False),
    ([_pr("0" * 40, None)], "tip-differs-from-pr", False),
    ([_pr("TIP", "SQUASH", state="OPEN")], "pr-open", False),
    ([_pr("TIP", "SQUASH", state="CLOSED")], "pr-closed", False),
    ([_pr("TIP", "SQUASH", base="release")], "pr-wrong-base", False),
    ([_pr("TIP", "SQUASH", number=1), _pr("TIP", "SQUASH", number=2)], "pr-ambiguous", True),
    ([_pr("TIP", None)], "merge-commit-unknown", True),
    ([_pr("TIP", "1" * 40)], "merge-commit-not-fetched", True),
    ([_pr("TIP", "TIP")], "merge-commit-not-on-default", False),
])
def test_merge_proof_refuses_unless_unambiguous(repo, merged, prs, code, unknown) -> None:
    feature, tip, squash = merged
    prs = [forge.PullRequest(p.number, p.state, p.base, p.head_branch, tip if p.head_sha == "TIP" else p.head_sha,
                             {"SQUASH": squash, "TIP": tip}.get(p.merge_commit or "", p.merge_commit),
                             p.cross_repository, p.url) for p in prs]
    row = _verdict(repo, feature, prs)
    assert code in _codes(row)
    assert row["verdict"] == ("unknown" if unknown else "blocked")


def test_pull_request_from_a_fork_is_not_proof(repo, merged) -> None:
    feature, tip, squash = merged
    assert "unmerged" in _codes(_verdict(repo, feature, [_pr(tip, squash, cross=True)]))


def test_forge_failure_is_unknown_not_merged(repo, merged) -> None:
    feature, _tip, _squash = merged
    row = _verdict(repo, feature, forge.forge_error(2, "gh failed"))
    assert row["verdict"] == "unknown" and "forge-unavailable" in _codes(row)


def test_dirty_untracked_and_unknown_ignored_files_block(repo, merged) -> None:
    feature, tip, squash = merged
    (feature / "a.txt").write_text("changed\n")
    (feature / "new.txt").write_text("x\n")
    (feature / "secrets.log").write_text("x\n")
    codes = _codes(_verdict(repo, feature, [_pr(tip, squash)]))
    assert {"uncommitted-changes", "untracked-files", "ignored-files"} <= codes


def test_disposable_caches_are_allowed_and_noted(repo, merged) -> None:
    feature, tip, squash = merged
    (feature / "__pycache__").mkdir()
    (feature / "__pycache__" / "x.pyc").write_text("x")
    row = _verdict(repo, feature, [_pr(tip, squash)])
    assert row["verdict"] == "eligible" and any("disposable" in note for note in row["notes"])


def test_gateway_work_blocks_and_an_unreadable_store_is_unknown(repo, merged) -> None:
    feature, tip, squash = merged
    busy = _verdict(repo, feature, [_pr(tip, squash)], active=lambda _p: {"requests": ["req_1"], "sessions": []})
    assert busy["verdict"] == "blocked" and "gateway-active-work" in _codes(busy)

    def unreadable(_path):
        raise RuntimeError("store unreadable")

    unknown = _verdict(repo, feature, [_pr(tip, squash)], active=unreadable)
    assert unknown["verdict"] == "unknown" and "active-work-unreadable" in _codes(unknown)


def test_primary_protected_detached_and_locked_are_refused(repo, merged, monkeypatch) -> None:
    feature, tip, squash = merged
    rows = {row["path"]: row for row in eligibility.assess_all(
        repo, active_work=lambda _p: {"requests": [], "sessions": []},
        pull_requests=lambda _r, _b: (_pr(tip, squash),))["worktrees"]}
    assert "primary" in _codes(rows[str(repo)])

    _git(repo, "worktree", "lock", str(feature))
    assert "git-locked" in _codes(_verdict(repo, feature, [_pr(tip, squash)]))
    _git(repo, "worktree", "unlock", str(feature))

    _git(feature, "checkout", "-q", "--detach")
    assert "detached-head" in _codes(_verdict(repo, feature, [_pr(tip, squash)]))
    _git(feature, "checkout", "-q", "feature")

    monkeypatch.setattr(eligibility.service, "protected_paths", lambda _repo: {feature: "shared runtime"})
    assert "protected" in _codes(_verdict(repo, feature, [_pr(tip, squash)]))


def test_process_using_the_path_blocks_and_unknown_platform_is_unknown(repo, merged, monkeypatch) -> None:
    feature, tip, squash = merged
    monkeypatch.setattr(eligibility, "pids_referencing_path", lambda _path: [os.getpid() + 1])
    assert "in-use" in _codes(_verdict(repo, feature, [_pr(tip, squash)]))
    monkeypatch.setattr(eligibility, "pids_referencing_path", lambda _path: None)
    row = _verdict(repo, feature, [_pr(tip, squash)])
    assert row["verdict"] == "unknown" and "processes-unknown" in _codes(row)


def test_assessment_never_modifies_the_repository(repo, merged) -> None:
    feature, tip, squash = merged
    before = (_git(repo, "worktree", "list", "--porcelain"), _git(repo, "branch", "--list"), _git(feature, "status", "--porcelain"))
    _verdict(repo, feature, [_pr(tip, squash)])
    assert before == (_git(repo, "worktree", "list", "--porcelain"), _git(repo, "branch", "--list"), _git(feature, "status", "--porcelain"))
    assert git.branch_exists(repo, "feature") and feature.is_dir()


def test_malformed_active_work_reply_is_unknown(repo, merged) -> None:
    feature, tip, squash = merged
    row = _verdict(repo, feature, [_pr(tip, squash)], active=lambda _p: {"requests": None})
    assert row["verdict"] == "unknown" and "active-work-unreadable" in _codes(row)


def test_a_full_page_of_pull_requests_is_incomplete_not_proof(monkeypatch, tmp_path) -> None:
    import json
    import subprocess

    rows = [{"number": n, "state": "MERGED", "baseRefName": "main", "headRefName": "f", "headRefOid": "a" * 40,
             "mergeCommit": {"oid": "b" * 40}, "isCrossRepository": False, "url": ""} for n in range(forge._LIMIT)]
    monkeypatch.setattr(forge.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(forge.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(rows), ""))
    with pytest.raises(Exception) as raised:
        forge.pull_requests_for_branch(tmp_path, "f")
    assert getattr(raised.value, "code", "") == "EXT-FORGE-005"
    monkeypatch.setattr(forge.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(rows[:2]), ""))
    assert [pr.number for pr in forge.pull_requests_for_branch(tmp_path, "f")] == [0, 1]


def test_ancestry_distinguishes_no_from_cannot_tell(repo, merged) -> None:
    feature, tip, squash = merged
    assert git.is_ancestor(repo, squash, "origin/main") is True
    assert git.is_ancestor(repo, tip, "origin/main") is False
    assert git.is_ancestor(repo, "1" * 40, "origin/main") is None
    assert git.is_ancestor(repo, tip, "origin/nope") is None
