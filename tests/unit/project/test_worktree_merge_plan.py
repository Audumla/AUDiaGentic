"""DW01 slice 4a: the read-only plan for publishing a worktree."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.commands import worktree as worktree_command
from audiagentic.components.project.worktrees import merge_plan
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import forge

IDLE = lambda _path: {"requests": [], "sessions": []}  # noqa: E731
ME = forge.RepositoryIdentity("Acme/Widget", "main", True)


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xstate"))
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
    _git(main, "remote", "set-url", "origin", "https://github.com/acme/widget.git")  # a GitHub-shaped remote
    return main.resolve()


@pytest.fixture
def feature(repo: Path) -> Path:
    path = (repo.parent / "feature").resolve()
    _git(repo, "worktree", "add", "-q", "-b", "me/feature", str(path), "origin/main")
    (path / "f.txt").write_text("f\n")
    _git(path, "add", "f.txt")
    _git(path, "commit", "-q", "-m", "feature")
    return path


def _pr(number=7, state="OPEN", base="main", branch="me/feature", sha="x", **kwargs) -> forge.PullRequest:
    return forge.PullRequest(number, state, base, branch, sha, None, False, f"https://example.invalid/{number}", **kwargs)


def _plan(repo, feature, prs=(), *, identity=ME, **kwargs):
    def who(_repo):
        if isinstance(identity, Exception):
            raise identity
        return identity

    return merge_plan.plan(repo, feature, active_work=kwargs.pop("active_work", IDLE),
                           pull_requests=lambda _r, _b: tuple(prs), identity=who, **kwargs)


def _codes(result: dict) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}


def _steps(result: dict) -> list[str]:
    return [operation["action"] for operation in result["operations"]]


def test_ready_plan_pushes_the_exact_tip_and_creates_the_pull_request(repo, feature) -> None:
    result = _plan(repo, feature, title="feat(thing): add the thing")
    tip = _git(feature, "rev-parse", "HEAD")
    assert result["verdict"] == "ready" and result["blockers"] == [] and result["dry-run"] is True
    assert f"git push origin {tip[:12]}:refs/heads/me/feature" in " ".join(_steps(result))
    assert "create" in _steps(result) and "enable squash auto-merge" in _steps(result)
    assert result["repository"] == "Acme/Widget"


@pytest.mark.parametrize("title, code", [(None, "title-required"), ("add the thing", "title-invalid"),
                                         ("feat: " + "x" * 120, "title-invalid"), ("feat(): nothing", "title-invalid")])
def test_a_new_pull_request_needs_a_valid_conventional_title(repo, feature, title, code) -> None:
    assert code in _codes(_plan(repo, feature, title=title))


def test_existing_open_pull_request_is_reused_and_behind_is_reported_not_fixed(repo, feature) -> None:
    result = _plan(repo, feature, [_pr(merge_state="BEHIND")])
    assert result["verdict"] == "ready" and result["pr"] == 7
    assert "reuse #7" in " ".join(_steps(result)) and any("BEHIND" in step for step in _steps(result))
    assert not any("update" in step and "branch" in step and "never" not in step for step in _steps(result))


def test_auto_merge_already_on_is_not_requested_again(repo, feature) -> None:
    assert "already enabled" in _steps(_plan(repo, feature, [_pr(auto_merge=True)]))


@pytest.mark.parametrize("pr, code", [(_pr(is_draft=True), "pr-draft"), (_pr(base="release"), "pr-wrong-base")])
def test_draft_or_wrong_base_pull_requests_block(repo, feature, pr, code) -> None:
    assert code in _codes(_plan(repo, feature, [pr]))


def test_several_open_pull_requests_are_ambiguous_and_unknown(repo, feature) -> None:
    result = _plan(repo, feature, [_pr(1), _pr(2)])
    assert result["verdict"] == "unknown" and "pr-ambiguous" in _codes(result)


def test_a_closed_pull_request_is_never_silently_replaced(repo, feature) -> None:
    result = _plan(repo, feature, [_pr(state="CLOSED")], title="feat(thing): again")
    assert "closed-pr-exists" in _codes(result) and result["verdict"] == "blocked"


def test_an_already_merged_tip_is_reported_not_republished(repo, feature) -> None:
    tip = _git(feature, "rev-parse", "HEAD")
    assert "already-merged" in _codes(_plan(repo, feature, [_pr(state="MERGED", sha=tip)], title="feat(x): y"))


def test_forks_do_not_count_as_this_branchs_pull_request(repo, feature) -> None:
    fork = forge.PullRequest(3, "OPEN", "main", "me/feature", "x", None, True, "u")
    assert "create" in _steps(_plan(repo, feature, [fork], title="feat(x): y"))


def test_remote_must_be_this_repository(repo, feature) -> None:
    other = forge.RepositoryIdentity("someone/else", "main", True)
    assert "remote-not-this-repository" in _codes(_plan(repo, feature, title="feat(x): y", identity=other))
    _git(repo, "remote", "set-url", "--push", "origin", "https://github.com/evil/widget.git")
    assert "remote-mismatch" in _codes(_plan(repo, feature, title="feat(x): y"))
    _git(repo, "remote", "set-url", "origin", str(repo.parent / "origin.git"))
    _git(repo, "remote", "set-url", "--push", "origin", str(repo.parent / "origin.git"))
    assert "remote-unreadable" in _codes(_plan(repo, feature, title="feat(x): y"))


def test_no_push_permission_and_forge_failures(repo, feature) -> None:
    assert "no-push-permission" in _codes(_plan(repo, feature, title="feat(x): y",
                                                identity=forge.RepositoryIdentity("Acme/Widget", "main", False)))
    down = _plan(repo, feature, title="feat(x): y", identity=forge.forge_error(2, "gh failed"))
    assert down["verdict"] == "unknown" and "forge-unavailable" in _codes(down)


def test_local_state_blockers(repo, feature) -> None:
    (feature / "f.txt").write_text("edited\n")
    (feature / "new.txt").write_text("x\n")
    assert "uncommitted-changes" in _codes(_plan(repo, feature, title="feat(x): y"))
    clean = (repo.parent / "same").resolve()
    _git(repo, "worktree", "add", "-q", "-b", "me/same", str(clean), "origin/main")
    assert "nothing-to-merge" in _codes(_plan(repo, clean, title="feat(x): y"))
    _git(feature, "checkout", "-q", "--", "f.txt")
    (feature / "new.txt").unlink()
    _git(feature, "checkout", "-q", "--detach")
    assert "detached-head" in _codes(_plan(repo, feature, title="feat(x): y"))


def test_confirmed_head_must_match_and_gateway_work_blocks(repo, feature) -> None:
    tip = _git(feature, "rev-parse", "HEAD")
    assert "head-mismatch" in _codes(_plan(repo, feature, title="feat(x): y", head="0" * 12))
    assert "head-mismatch" not in _codes(_plan(repo, feature, title="feat(x): y", head=tip[:12]))
    busy = _plan(repo, feature, title="feat(x): y", active_work=lambda _p: {"requests": ["r"], "sessions": []})
    assert "gateway-active-work" in _codes(busy)
    broken = _plan(repo, feature, title="feat(x): y", active_work=lambda _p: {"requests": None})
    assert broken["verdict"] == "unknown" and "active-work-unreadable" in _codes(broken)


def test_the_main_worktree_cannot_be_planned(repo, feature) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        _plan(repo, repo, title="feat(x): y")
    assert raised.value.code == "CON-WTMERGE-001"


def test_planning_changes_nothing(repo, feature) -> None:
    before = (_git(repo, "worktree", "list", "--porcelain"), _git(repo, "branch", "--list"),
              _git(feature, "status", "--porcelain"), _git(repo, "for-each-ref"))
    _plan(repo, feature, title="feat(x): y")
    assert before == (_git(repo, "worktree", "list", "--porcelain"), _git(repo, "branch", "--list"),
                      _git(feature, "status", "--porcelain"), _git(repo, "for-each-ref"))


@pytest.mark.parametrize("url, slug", [
    ("https://github.com/Acme/Widget.git", "acme/widget"), ("git@github.com:acme/widget.git", "acme/widget"),
    ("ssh://git@github.com/acme/widget", "acme/widget"), ("https://x-access-token:SECRET@github.com/acme/widget.git", "acme/widget"),
    ("/some/local/path.git", None), ("", None), (None, None)])
def test_repository_slug_never_returns_credentials(url, slug) -> None:
    assert merge_plan.repository_slug(url) == slug
    assert "SECRET" not in (merge_plan.repository_slug(url) or "")


def test_command_without_dry_run_executes_and_refuses_on_blockers(capsys) -> None:
    assert worktree_command.dispatch_keyword(["merge"]) == 1
    assert "CON-WTMERGE-003" in capsys.readouterr().err
    assert worktree_command.dispatch_keyword(["merge", "dry-run", "no"]) == 2
