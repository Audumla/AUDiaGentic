"""DW03: audit trail, evidence hold and adopt."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.project.worktrees import audit, lifecycle, provenance, records, tidy as tidier
from audiagentic.components.source_control import git_api as git
from audiagentic.foundation.contracts.errors import AudiaGenticError

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
IDLE = lambda _path: {"requests": [], "sessions": []}  # noqa: E731


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


def test_start_is_audited_and_the_trail_outlives_the_record(repo: Path) -> None:
    started = lifecycle.start(repo, "task-a", purpose="try it", plan_item="DW03")
    records.forget(repo, started.worktree_id)
    events = audit.read(repo)
    assert [e["action"] for e in events] == ["start"]
    assert events[0]["purpose"] == "try it" and events[0]["branch"] == "alice/task-a"
    assert records.read_records(repo) == {}  # record gone, trail stays


def test_a_damaged_audit_line_is_reported_not_skipped(repo: Path) -> None:
    lifecycle.start(repo, "task-a", purpose="x")
    path = next((Path(os.environ["XDG_STATE_HOME"]) / "audiagentic" / "worktrees" / "audit").glob("*.jsonl"), None)
    if path is None:  # state dir name differs by platform: find it
        path = next(Path(os.environ["XDG_STATE_HOME"]).rglob("*.jsonl"))
    path.write_text(path.read_text() + "{not json\n")
    with pytest.raises(AudiaGenticError) as raised:
        audit.read(repo)
    assert raised.value.code == "VAL-WTAUD-001"


def test_a_failed_audit_append_never_stops_the_action(repo: Path, monkeypatch) -> None:
    def full(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(audit, "_path", full)
    started = lifecycle.start(repo, "task-a", purpose="x")
    assert started.path.is_dir() and started.worktree_id in records.read_records(repo)


def test_an_evidence_hold_blocks_prune_tidy_and_record_removal_until_cleared(repo: Path) -> None:
    from audiagentic.components.project.worktrees import eligibility

    started = lifecycle.start(repo, "task-a", purpose="x")
    provenance.set_evidence(repo, started.path, "experiment results not yet saved")
    rows = eligibility.assess_all(repo, active_work=IDLE, pull_requests=lambda _r, _b: ())["worktrees"]
    row = next(r for r in rows if r["path"] == str(started.path))
    assert "evidence-hold" in [b["code"] for b in row["blockers"]] and row["verdict"] == "blocked"

    with pytest.raises(AudiaGenticError) as raised:
        records.forget(repo, started.worktree_id)
    assert raised.value.code == "VAL-WTREC-004"

    provenance.clear_evidence(repo, started.path)
    assert records.read_records(repo)[started.worktree_id].evidence is None
    assert [e["action"] for e in audit.read(repo)] == ["start", "evidence-set", "evidence-cleared"]


def test_a_held_orphan_record_survives_tidy(repo: Path) -> None:
    started = lifecycle.start(repo, "task-a", purpose="x")
    provenance.set_evidence(repo, started.path, "keep")
    _git(repo, "worktree", "remove", "--force", str(started.path))  # plain git bypasses the hold, the record stays
    result = tidier.tidy(repo, active_work=IDLE, apply=True, pull_requests=lambda _r, _b: ())
    assert result["records-retired"] == []
    assert started.worktree_id in records.read_records(repo)


def test_evidence_needs_a_reason_and_a_record(repo: Path, tmp_path: Path) -> None:
    started = lifecycle.start(repo, "task-a", purpose="x")
    with pytest.raises(AudiaGenticError) as raised:
        provenance.set_evidence(repo, started.path, "  ")
    assert raised.value.code == "VAL-WTPROV-002"
    stray = tmp_path / "stray"
    _git(repo, "worktree", "add", "-q", "-b", "stray", str(stray))
    with pytest.raises(AudiaGenticError) as raised:
        provenance.set_evidence(repo, stray, "why")
    assert raised.value.code == "VAL-WTPROV-001"


def test_adopt_records_a_plain_git_worktree_honestly(repo: Path, tmp_path: Path) -> None:
    stray = tmp_path / "stray"
    _git(repo, "worktree", "add", "-q", "-b", "stray", str(stray))
    unmanaged = records.reconcile(git.list_worktrees(repo), records.read_records(repo)).unmanaged
    assert stray.resolve() in [e.path for e in unmanaged]

    record = provenance.adopt(repo, stray, purpose="hand-made experiment", plan_item="DW03")
    assert record.adopted and record.adopted_by == "Alice" and record.branch == "stray"
    unmanaged = records.reconcile(git.list_worktrees(repo), records.read_records(repo)).unmanaged
    assert stray.resolve() not in [e.path for e in unmanaged]
    assert audit.read(repo)[-1]["action"] == "adopt"

    with pytest.raises(AudiaGenticError) as raised:
        provenance.adopt(repo, stray, purpose="again")
    assert raised.value.code == "VAL-WTPROV-007"


def test_adopt_refuses_the_primary_a_non_worktree_and_a_missing_purpose(repo: Path, tmp_path: Path) -> None:
    for path, purpose, code in ((repo, "x", "VAL-WTPROV-005"), (tmp_path / "nope", "x", "VAL-WTPROV-004"),
                                (repo, " ", "VAL-WTPROV-003")):
        with pytest.raises(AudiaGenticError) as raised:
            provenance.adopt(repo, path, purpose=purpose)
        assert raised.value.code == code
