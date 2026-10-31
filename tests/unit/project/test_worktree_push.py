"""DW01 slice 4b: configured checks, then one commit-bound non-force push."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from audiagentic.components.project.worktrees import merge_plan, publish
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import forge

IDLE = lambda _path: {"requests": [], "sessions": []}  # noqa: E731
ME = forge.RepositoryIdentity("Acme/Widget", "main", True)
GITHUB = "https://github.com/acme/widget.git"


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    """A repository whose origin is a local bare repo that the code believes is a GitHub URL."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xstate"))
    monkeypatch.setenv("GH_TOKEN", "SECRET-TOKEN")
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
    real = merge_plan.git.remote_url
    monkeypatch.setattr(merge_plan.git, "remote_url", lambda repo, remote="origin", *, push=False: GITHUB)
    feature = (tmp_path / "feature").resolve()
    _git(main, "worktree", "add", "-q", "-b", "me/feature", str(feature), "origin/main")
    (feature / "f.txt").write_text("f\n")
    _git(feature, "add", "f.txt")
    _git(feature, "commit", "-q", "-m", "feature")
    return {"repo": main.resolve(), "feature": feature, "bare": bare, "state": tmp_path / "state", "real": real,
            "tmp": tmp_path}


def _project_settings(repo: Path, text: str) -> None:
    target = repo / ".audiagentic" / "settings.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("schema_version: 1\n" + text)


def _user_settings(tmp: Path, text: str) -> None:
    target = tmp / "xdg" / "audiagentic" / "settings.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("schema_version: 1\n" + text)


def _push(world, **kwargs):
    return publish.push(world["repo"], world["feature"], active_work=IDLE, identity=lambda _r: ME,
                        state_root=world["state"], **kwargs)


def _remote_tip(world) -> str | None:
    try:
        return _git(world["bare"], "rev-parse", "refs/heads/me/feature")
    except subprocess.CalledProcessError:
        return None


def _argv(code: str) -> str:
    return json.dumps([sys.executable, "-c", code])


def test_push_without_checks_publishes_exactly_the_tip_and_confirms_it(world) -> None:
    tip = _git(world["feature"], "rev-parse", "HEAD")
    result = _push(world)
    assert result["pushed"] is True and result["remote-commit"] == tip == _remote_tip(world)
    receipt = json.loads(next((world["state"] / "worktrees" / "receipts").rglob("*.json")).read_text())
    assert receipt["phase"] == "VERIFIED" and receipt["tip"] == tip and {"STARTED", "CHECKED", "PUSHED"} <= set(receipt["phases"])


def test_dry_run_runs_and_sends_nothing(world) -> None:
    _project_settings(world["repo"], "worktrees:\n  pre-push: [guard]\n")
    _user_settings(world["tmp"], f"worktrees:\n  checks:\n    guard: {_argv('raise SystemExit(9)')}\n")
    result = _push(world, dry_run=True)
    assert result["dry-run"] is True and result["checks"] == ["guard"] and _remote_tip(world) is None
    assert not (world["state"] / "worktrees" / "receipts").exists()


def test_checks_run_against_the_tip_with_a_minimal_environment(world) -> None:
    out = world["tmp"] / "seen.json"
    code = ("import json,os,sys;json.dump({'argv':sys.argv[1:],'token':'GH_TOKEN' in os.environ,'cwd':os.getcwd()},"
            f"open({str(out)!r},'w'))")
    _project_settings(world["repo"], "worktrees:\n  pre-push: [guard]\n")
    _user_settings(world["tmp"], "worktrees:\n  checks:\n    guard: " + json.dumps(
        [sys.executable, "-c", code, "{tip}", "{base}", "{worktree}"]) + "\n")
    tip = _git(world["feature"], "rev-parse", "HEAD")
    base = _git(world["repo"], "rev-parse", "origin/main")
    _push(world)
    seen = json.loads(out.read_text())
    assert seen["argv"] == [tip, base, str(world["feature"])] and seen["token"] is False
    assert Path(seen["cwd"]).resolve() == world["feature"]


def test_a_failing_check_stops_everything_before_the_push(world) -> None:
    _project_settings(world["repo"], "worktrees:\n  pre-push: [guard]\n")
    _user_settings(world["tmp"], f"worktrees:\n  checks:\n    guard: {_argv('print(1); raise SystemExit(3)')}\n")
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code == "CON-WTPUSH-004" and "exit 3" in raised.value.message and _remote_tip(world) is None


def test_commands_come_only_from_user_settings(world) -> None:
    _project_settings(world["repo"], "worktrees:\n  pre-push: [guard]\n")
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code == "CON-WTPUSH-003" and _remote_tip(world) is None
    _project_settings(world["repo"], f"worktrees:\n  pre-push: [guard]\n  checks:\n    guard: {_argv('pass')}\n")
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code in {"CFG-SET-004", "CON-WTPUSH-002"} and _remote_tip(world) is None  # schema first, then the tool


def test_a_missing_executable_fails_closed(world) -> None:
    _project_settings(world["repo"], "worktrees:\n  pre-push: [guard]\n")
    _user_settings(world["tmp"], "worktrees:\n  checks:\n    guard: [definitely-not-a-real-program-xyz]\n")
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code == "CON-WTPUSH-004" and "not found" in raised.value.message


def test_a_commit_made_while_the_checks_run_is_never_pushed(world) -> None:
    feature = world["feature"]
    code = ("import subprocess;subprocess.run(['git','-c','user.name=t','-c','user.email=t@e.invalid','commit',"
            "'--allow-empty','-q','-m','sneaky'],check=True)")
    _project_settings(world["repo"], "worktrees:\n  pre-push: [guard]\n")
    _user_settings(world["tmp"], f"worktrees:\n  checks:\n    guard: {_argv(code)}\n")
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code == "CON-WTPUSH-005" and _remote_tip(world) is None
    assert _git(feature, "log", "-1", "--format=%s") == "sneaky"


def test_a_diverged_remote_branch_is_never_overwritten(world) -> None:
    other = world["tmp"] / "other"
    _git(world["tmp"], "clone", "-q", str(world["bare"]), str(other))
    _git(other, "checkout", "-q", "-b", "me/feature")
    (other / "x.txt").write_text("x\n")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "someone else")
    _git(other, "push", "-q", "origin", "me/feature")
    theirs = _remote_tip(world)
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code == "CON-WTPUSH-006" and _remote_tip(world) == theirs


def test_blockers_refuse_before_any_check_runs(world) -> None:
    (world["feature"] / "f.txt").write_text("edited\n")
    ran = []
    with pytest.raises(AudiaGenticError) as raised:
        publish.push(world["repo"], world["feature"], active_work=IDLE, identity=lambda _r: ME,
                     state_root=world["state"], run=lambda *a, **k: ran.append(1))
    assert raised.value.code == "CON-WTPUSH-001" and "uncommitted-changes" in raised.value.message and not ran
    assert _remote_tip(world) is None


def test_confirmed_head_must_match(world) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        _push(world, head="0" * 12)
    assert raised.value.code == "CON-WTPUSH-001" and "head-mismatch" in raised.value.message


def test_a_project_cannot_drop_a_check_the_user_requires(world) -> None:
    _project_settings(world["repo"], "worktrees:\n  pre-push: []\n")
    _user_settings(world["tmp"], f"worktrees:\n  pre-push: [guard]\n  checks:\n    guard: {_argv('raise SystemExit(4)')}\n")
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code == "CON-WTPUSH-004" and _remote_tip(world) is None


def test_repository_hooks_do_not_run_on_the_push(world) -> None:
    hook = world["repo"] / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    assert _push(world)["pushed"] is True and _remote_tip(world) is not None


def test_remote_readback_is_strict(monkeypatch, tmp_path) -> None:
    from audiagentic.foundation.system import git

    def answer(text):
        monkeypatch.setattr(git, "run_git", lambda *a, **k: text)
        return git.remote_branch_commit(tmp_path, "origin", "me/feature")

    good = "a" * 40
    assert answer(f"{good}\trefs/heads/me/feature\n") == good and answer("") is None
    for bad in (f"{good}\trefs/heads/me/feature\n{good}\trefs/heads/me/feature\n", f"{good}\trefs/heads/other\n",
                "zz\trefs/heads/me/feature\n", "not a record\n"):
        with pytest.raises(AudiaGenticError):
            answer(bad)


def test_a_malformed_check_command_is_refused(world) -> None:
    _project_settings(world["repo"], "worktrees:\n  pre-push: [guard]\n")
    _user_settings(world["tmp"], "worktrees:\n  checks:\n    guard: [python3, '']\n")
    with pytest.raises(AudiaGenticError) as raised:
        _push(world)
    assert raised.value.code in {"CFG-SET-004", "CON-WTPUSH-002"} and _remote_tip(world) is None  # schema first, then the tool
