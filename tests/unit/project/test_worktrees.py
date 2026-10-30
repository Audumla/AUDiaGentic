"""DW01 slice 1: git adapter, central ownership records, list and primary-checkout checks."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.commands import worktree as worktree_command
from audiagentic.components.project.doctor_checks import check_primary_checkout
from audiagentic.components.project.worktrees import records, service
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.lifecycle.doctor import OK, WARN
from audiagentic.foundation.system import git
from audiagentic.foundation.system.process import pids_referencing_path


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A main worktree on `main` with a bare `origin` whose HEAD is `main`."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    main = tmp_path / "main"
    _git(tmp_path, "clone", "-q", str(remote), str(main))
    _git(main, "checkout", "-q", "-b", "main")
    (main / "a.txt").write_text("one\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-q", "-m", "one")
    _git(main, "push", "-q", "-u", "origin", "main")
    _git(main, "remote", "set-head", "origin", "main")
    return main.resolve()


def _add_worktree(repo: Path, name: str, *, branch: str) -> Path:
    path = repo.parent / name
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), "origin/main")
    return path.resolve()


def test_adapter_lists_worktrees_and_reports_facts(repo: Path) -> None:
    feature = _add_worktree(repo, "feature", branch="feature")
    entries = git.list_worktrees(repo)
    assert [(entry.path, entry.branch) for entry in entries] == [(repo, "main"), (feature, "feature")]
    assert git.default_branch(repo) == "origin/main"
    assert git.common_dir(feature) == git.common_dir(repo)
    assert git.ahead_behind(feature, "origin/main") == (0, 0)
    (feature / "b.txt").write_text("x\n")
    _git(feature, "add", "b.txt")
    _git(feature, "commit", "-q", "-m", "two")
    (feature / "a.txt").write_text("changed\n")
    (feature / "c.txt").write_text("new\n")
    assert git.ahead_behind(feature, "origin/main") == (1, 0)
    assert git.changes(feature) == (1, 1)
    assert git.ahead_behind(feature, "origin/nope") is None


def test_git_failures_are_typed(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        git.list_worktrees(tmp_path)  # not a repository
    assert raised.value.code == "EXT-GIT-002"


def test_records_are_central_and_reconciled_with_git(repo: Path, tmp_path: Path) -> None:
    feature = _add_worktree(repo, "feature", branch="feature")
    state = tmp_path / "records"
    record = records.WorktreeRecord(
        worktree_id=records.new_worktree_id(), path=str(feature), branch="feature",
        owner={"session": "s1", "harness": "claude", "account": "a"}, created_at="2026-10-30T00:00:00Z",
        purpose="test", plan_item="DW01")
    records.register(repo, record, state_root=state)
    assert records.read_records(repo, state_root=state) == {record.worktree_id: record}
    # Nothing was written into either worktree.
    assert _git(feature, "status", "--porcelain") == ""
    assert not any(path.name == ".audiagentic" for path in feature.iterdir())

    ghost = records.WorktreeRecord(
        worktree_id=records.new_worktree_id(), path=str(repo.parent / "gone"), branch="gone",
        owner={}, created_at="2026-10-30T00:00:00Z")
    records.register(repo, ghost, state_root=state)
    result = records.reconcile(git.list_worktrees(repo), records.read_records(repo, state_root=state))
    assert set(result.paired) == {feature}
    assert [entry.path for entry in result.unmanaged] == [repo]
    assert [orphan.worktree_id for orphan in result.orphans] == [ghost.worktree_id]

    assert records.forget(repo, ghost.worktree_id, state_root=state) is True
    assert records.forget(repo, ghost.worktree_id, state_root=state) is False


def test_conflicting_records_and_corrupt_store_are_refused(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "records"
    first = records.WorktreeRecord(records.new_worktree_id(), str(repo), "main", {}, "2026-10-30T00:00:00Z")
    records.register(repo, first, state_root=state)
    records.register(repo, first, state_root=state)  # idempotent
    clash = records.WorktreeRecord(records.new_worktree_id(), str(repo), "x", {}, "2026-10-30T00:00:00Z")
    with pytest.raises(AudiaGenticError) as raised:
        records.register(repo, clash, state_root=state)
    assert raised.value.code == "VAL-WTREC-003"
    with pytest.raises(AudiaGenticError) as raised:
        records.register(repo, records.WorktreeRecord("bad", str(repo), None, {}, "x"), state_root=state)
    assert raised.value.code == "VAL-WTREC-002"

    store = next(state.rglob("*.json"))
    store.write_text("{not json", encoding="utf-8")
    with pytest.raises(AudiaGenticError) as raised:
        records.read_records(repo, state_root=state)
    assert raised.value.code == "VAL-WTREC-001"  # unreadable is never "empty"


def test_list_rows_report_state_ownership_and_protection(repo: Path, tmp_path: Path, monkeypatch) -> None:
    feature = _add_worktree(repo, "feature", branch="feature")
    (feature / "a.txt").write_text("edited\n")
    state = tmp_path / "records"
    records.register(repo, records.WorktreeRecord(
        records.new_worktree_id(), str(feature), "feature", {"session": "s1"}, "2026-10-30T00:00:00Z",
        purpose="p", plan_item="DW01"), state_root=state)
    monkeypatch.setattr(service, "protected_paths", lambda _repo: {repo: "runtime"})

    result = service.list_rows(repo, state_root=state)

    assert result["default-branch"] == "origin/main"
    primary, task = result["worktrees"]
    assert primary["primary"] and primary["protected"] == "runtime" and not primary["managed"]
    assert task["branch"] == "feature" and task["changes"] == 1 and task["managed"]
    assert task["owner"] == {"session": "s1"} and task["plan-item"] == "DW01"
    assert (task["ahead"], task["behind"]) == (0, 0)
    assert task["pr"] is None  # unknown until the forge adapter exists
    assert result["orphan-records"] == []


def test_process_scan_sees_a_process_inside_a_worktree(repo: Path) -> None:
    pids = pids_referencing_path(repo)
    if pids is None:
        pytest.skip("this platform cannot inspect other processes")
    assert pids == []
    child = subprocess.Popen(["sleep", "30"], cwd=repo)
    try:
        assert child.pid in (pids_referencing_path(repo) or [])
    finally:
        child.kill()
        child.wait()


def test_primary_checkout_problems_and_doctor(repo: Path) -> None:
    assert service.primary_checkout_problems(repo) == []
    assert check_primary_checkout(type("Ctx", (), {"project": repo})())[0].status == OK

    (repo / "local.txt").write_text("local\n")
    _git(repo, "add", "local.txt")
    _git(repo, "commit", "-q", "-m", "local only")
    other = _add_worktree(repo, "other", branch="other")
    (other / "up.txt").write_text("up\n")
    _git(other, "add", "up.txt")
    _git(other, "commit", "-q", "-m", "upstream")
    _git(other, "push", "-q", "origin", "other:main")
    _git(repo, "fetch", "-q")
    problems = service.primary_checkout_problems(repo)
    assert problems and "diverged" in problems[0]
    result = check_primary_checkout(type("Ctx", (), {"project": repo})())[0]
    assert result.status == WARN and "archive/" in (result.fix or "")

    _git(repo, "checkout", "-q", "-b", "wip")
    assert "not main" in service.primary_checkout_problems(repo)[0]


def test_command_grammar_and_output(repo: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(service, "protected_paths", lambda _repo: {})
    assert worktree_command.dispatch_keyword(["help"]) == 0
    assert "worktree list" in capsys.readouterr().out
    for bad in (["list", "--json"], ["list", "output"], ["list", "output", "xml"], ["list", "project"],
                ["frobnicate"], ["list", "project", str(repo), "project", str(repo)]):
        assert worktree_command.dispatch_keyword(bad) == 2, bad
    capsys.readouterr()
    assert worktree_command.dispatch_keyword(["list", "project", str(repo), "output", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["worktrees"][0]["branch"] == "main"
    assert worktree_command.dispatch_keyword(["list", "project", str(repo)]) == 0
    assert str(repo) in capsys.readouterr().out
