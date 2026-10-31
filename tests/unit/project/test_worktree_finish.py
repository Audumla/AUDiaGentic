"""DW01 slice 3b-2: finishing a merged worktree preserves first and removes only when nothing changed."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.project.worktrees import finish as finisher
from audiagentic.components.project.worktrees import records
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import forge, git, worktree_drain

IDLE = lambda _path: {"requests": [], "sessions": []}  # noqa: E731


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "state-root"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xstate"))
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    main = tmp_path / "main"
    _git(tmp_path, "clone", "-q", str(remote), str(main))
    _git(main, "checkout", "-q", "-b", "main")
    (main / ".gitignore").write_text("*.log\n__pycache__/\n.audiagentic/runtime/\n")
    (main / "a.txt").write_text("one\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "one")
    _git(main, "push", "-q", "-u", "origin", "main")
    _git(main, "remote", "set-head", "origin", "main")
    return main.resolve()


@pytest.fixture
def merged(repo: Path) -> tuple[Path, str, forge.PullRequest]:
    feature = (repo.parent / "feature").resolve()
    _git(repo, "worktree", "add", "-q", "-b", "me/feature", str(feature), "origin/main")
    (feature / "f.txt").write_text("f\n")
    _git(feature, "add", "f.txt")
    _git(feature, "commit", "-q", "-m", "feature")
    tip = _git(feature, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("f\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "squash")
    _git(repo, "push", "-q", "origin", "main")
    squash = _git(repo, "rev-parse", "HEAD")
    return feature, tip, forge.PullRequest(9, "MERGED", "main", "me/feature", tip, squash, False, "")


def _run(repo, state, feature, pr, **kwargs):
    return finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: (pr,),
                           state_root=state, **kwargs)


def test_finish_preserves_then_removes_and_cleans_up(repo, merged, state) -> None:
    feature, tip, pr = merged
    (feature / "__pycache__").mkdir()
    (feature / "__pycache__" / "x.pyc").write_text("x")
    (feature / ".audiagentic" / "runtime").mkdir(parents=True)
    (feature / ".audiagentic" / "runtime" / "req.json").write_text('{"a": 1}')

    result = _run(repo, state, feature, pr)

    assert not feature.exists()
    assert not git.branch_exists(repo, "me/feature")
    assert git.resolve_commit(repo, result["quarantine-ref"]) == tip
    archived = Path(result["archive"]) / ".audiagentic" / "runtime" / "req.json"
    assert archived.read_text() == '{"a": 1}'
    assert not worktree_drain.is_draining(feature, state_root=state)
    journal = finisher._read_journal(finisher._journal_path(state, repo, feature))
    assert journal["phase"] == "COMPLETE" and journal["proof"]["pr"] == 9


def test_finish_refuses_unmerged_and_leaves_everything_in_place(repo, merged, state) -> None:
    feature, tip, _pr = merged
    with pytest.raises(AudiaGenticError) as raised:
        finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: (), state_root=state)
    assert raised.value.code == "CON-WTFIN-002"
    assert feature.is_dir() and git.branch_exists(repo, "me/feature")
    assert not worktree_drain.is_draining(feature, state_root=state)
    assert git.resolve_commit(repo, "refs/quarantine/x") is None


def test_dirty_worktree_is_never_finished(repo, merged, state) -> None:
    feature, _tip, pr = merged
    (feature / "f.txt").write_text("changed\n")
    with pytest.raises(AudiaGenticError) as raised:
        _run(repo, state, feature, pr)
    assert raised.value.code == "CON-WTFIN-002" and feature.is_dir()


def test_unknown_ignored_files_need_the_exact_count(repo, merged, state) -> None:
    feature, _tip, pr = merged
    (feature / "a.log").write_text("x")
    (feature / "b.log").write_text("x")
    with pytest.raises(AudiaGenticError) as raised:
        _run(repo, state, feature, pr)
    assert raised.value.code == "CON-WTFIN-003" and feature.is_dir()
    with pytest.raises(AudiaGenticError) as raised:
        _run(repo, state, feature, pr, discard_ignored=1)
    assert raised.value.code == "CON-WTFIN-003" and feature.is_dir()
    _run(repo, state, feature, pr, discard_ignored=2)
    assert not feature.exists()


def test_a_change_between_the_two_checks_aborts_before_removal(repo, merged, state) -> None:
    feature, tip, pr = merged
    calls = []

    def changing(_repo, _branch):
        calls.append(1)
        if len(calls) == 1:
            return (pr,)
        return (forge.PullRequest(10, "MERGED", "main", "me/feature", tip, pr.merge_commit, False, ""),)

    with pytest.raises(AudiaGenticError) as raised:
        finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=changing, state_root=state)
    assert raised.value.code == "CON-WTFIN-004"
    assert feature.is_dir() and git.branch_exists(repo, "me/feature")
    assert not worktree_drain.is_draining(feature, state_root=state)


def test_branch_that_moved_is_left_in_place(repo, merged, state, monkeypatch) -> None:
    feature, tip, pr = merged
    real_remove = git.remove_clean_worktree

    def remove_then_move(main, path):
        real_remove(main, path)
        _git(main, "update-ref", "refs/heads/me/feature", _git(main, "rev-parse", "origin/main"))

    monkeypatch.setattr(finisher.git, "remove_clean_worktree", remove_then_move)
    result = _run(repo, state, feature, pr)
    assert git.branch_exists(repo, "me/feature") and any("moved" in note for note in result["notes"])


def test_crash_after_removal_resumes_from_the_journal(repo, merged, state, monkeypatch) -> None:
    feature, tip, pr = merged
    monkeypatch.setattr(finisher.git, "delete_branch_at", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        _run(repo, state, feature, pr)
    assert not feature.exists() and git.branch_exists(repo, "me/feature")
    assert finisher._read_journal(finisher._journal_path(state, repo, feature))["phase"] == "WORKTREE_REMOVED"

    monkeypatch.undo()
    result = finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: (), state_root=state)
    assert not git.branch_exists(repo, "me/feature") and result["tip"] == tip
    assert finisher._read_journal(finisher._journal_path(state, repo, feature))["phase"] == "COMPLETE"


def test_primary_and_unknown_targets_are_refused(repo, merged, state) -> None:
    feature, _tip, pr = merged
    for target in (str(repo), "nope"):
        with pytest.raises(AudiaGenticError) as raised:
            finisher.finish(repo, target, active_work=IDLE, pull_requests=lambda _r, _b: (pr,), state_root=state)
        assert raised.value.code == "CON-WTFIN-001"
    assert feature.is_dir()


def test_record_is_forgotten_after_finish(repo, merged, state) -> None:
    feature, _tip, pr = merged
    records.register(repo, records.WorktreeRecord("wt_aaaaaaaaaaaa", str(feature), "me/feature", {"account": "x"},
                                                  "2026-10-30T00:00:00Z"), state_root=state)
    _run(repo, state, feature, pr)
    assert records.read_records(repo, state_root=state) == {}


def test_crash_between_intent_and_removal_resumes(repo, merged, state, monkeypatch) -> None:
    feature, tip, pr = merged
    real_remove = git.remove_clean_worktree

    def removed_then_died(main, path):
        real_remove(main, path)
        raise RuntimeError("died after git removed it")

    monkeypatch.setattr(finisher.git, "remove_clean_worktree", removed_then_died)
    with pytest.raises(AudiaGenticError):
        _run(repo, state, feature, pr)
    assert not feature.exists()
    assert finisher._read_journal(finisher._journal_path(state, repo, feature))["phase"] == "REMOVING"
    assert worktree_drain.is_draining(feature, state_root=state)  # ambiguous: the fence stays

    monkeypatch.undo()
    result = finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: (), state_root=state)
    assert result["tip"] == tip and not git.branch_exists(repo, "me/feature")
    assert not worktree_drain.is_draining(feature, state_root=state)


def test_a_journal_from_another_repository_is_not_resumed(repo, merged, state, tmp_path) -> None:
    feature, _tip, pr = merged
    journal = finisher._journal_path(state, repo, feature)
    finisher._write_journal(journal, {"path": str(feature), "proof": {
        "branch": "me/feature", "head": "0" * 40, "pr": 1, "identity": {"common-dir": str(tmp_path / "elsewhere.git")}}},
        "WORKTREE_REMOVED")
    _git(repo, "worktree", "remove", str(feature))
    with pytest.raises(AudiaGenticError) as raised:
        finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: (), state_root=state)
    assert raised.value.code == "CON-WTFIN-001" and git.branch_exists(repo, "me/feature")


def test_replacing_ignored_files_between_checks_aborts(repo, merged, state, monkeypatch) -> None:
    feature, tip, pr = merged
    (feature / "a.log").write_text("x")
    calls = []

    def swap(_repo, _branch):
        calls.append(1)
        if len(calls) == 2:  # between the first and second assessment
            (feature / "a.log").unlink()
            (feature / "b.log").write_text("y")
        return (pr,)

    with pytest.raises(AudiaGenticError) as raised:
        finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=swap, state_root=state, discard_ignored=1)
    assert raised.value.code == "CON-WTFIN-004" and feature.is_dir()


def test_archive_keeps_symlinks_and_never_overwrites(repo, merged, state) -> None:
    feature, tip, pr = merged
    records_dir = feature / ".audiagentic" / "runtime"
    records_dir.mkdir(parents=True)
    (records_dir / "req.json").write_text("{}")
    (records_dir / "link").symlink_to("/nonexistent/target")
    result = _run(repo, state, feature, pr)
    archived = Path(result["archive"]) / ".audiagentic" / "runtime"
    assert (archived / "link").is_symlink() and os.readlink(archived / "link") == "/nonexistent/target"
    assert (archived / "req.json").read_text() == "{}"


def test_special_files_in_records_refuse_before_removal(repo, merged, state) -> None:
    feature, _tip, pr = merged
    records_dir = feature / ".audiagentic" / "runtime"
    records_dir.mkdir(parents=True)
    (records_dir / "req.json").write_text("{}")
    os.mkfifo(records_dir / "pipe")
    with pytest.raises(AudiaGenticError) as raised:
        _run(repo, state, feature, pr)
    assert raised.value.code == "CON-WTFIN-005" and feature.is_dir()


def test_ambiguous_removal_failure_keeps_the_fence(repo, merged, state, monkeypatch) -> None:
    feature, _tip, pr = merged

    def damage_then_fail(_main, path):
        (path / "a.txt").unlink()  # git touched the tree before failing
        raise RuntimeError("partial removal")

    monkeypatch.setattr(finisher.git, "remove_clean_worktree", damage_then_fail)
    with pytest.raises(AudiaGenticError) as raised:
        _run(repo, state, feature, pr)
    assert raised.value.code == "CON-WTFIN-007"
    assert worktree_drain.is_draining(feature, state_root=state)


def test_an_earlier_journal_is_kept_not_overwritten(repo, merged, state) -> None:
    feature, _tip, pr = merged
    journal = finisher._journal_path(state, repo, feature)
    finisher._write_journal(journal, {"transaction": "oldtx", "path": str(feature), "proof": {}}, "PRESERVED")
    _run(repo, state, feature, pr)
    assert journal.with_name(f"{journal.stem}.oldtx.json").is_file()
    assert finisher._read_journal(journal)["phase"] == "COMPLETE"


@pytest.fixture
def unmerged(repo: Path) -> tuple[Path, str]:
    """A worktree with two commits that exist nowhere else."""
    feature = (repo.parent / "wip").resolve()
    _git(repo, "worktree", "add", "-q", "-b", "me/wip", str(feature), "origin/main")
    for name in ("one", "two"):
        (feature / f"{name}.txt").write_text(name)
        _git(feature, "add", f"{name}.txt")
        _git(feature, "commit", "-q", "-m", name)
    return feature, _git(feature, "rev-parse", "HEAD")


def _abandon(repo, state, feature, tip, *, prs=(), **kwargs):
    return finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: tuple(prs),
                           state_root=state, abandon=tip[:12], **kwargs)


def test_unmerged_work_is_refused_with_the_abandon_hint(repo, unmerged, state) -> None:
    feature, tip = unmerged
    with pytest.raises(AudiaGenticError) as raised:
        finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: (), state_root=state)
    assert raised.value.code == "CON-WTFIN-002" and f"abandon {tip[:12]}" in raised.value.message
    assert feature.is_dir()


def test_abandon_bundles_the_unique_commits_then_removes(repo, unmerged, state) -> None:
    feature, tip = unmerged
    result = _abandon(repo, state, feature, tip)
    assert not feature.exists() and not git.branch_exists(repo, "me/wip")
    assert git.resolve_commit(repo, result["quarantine-ref"]) == tip and result["abandoned"] is True
    bundle = Path(result["bundle"]["path"])
    assert bundle.is_file() and result["bundle"]["commits"] == 2
    import hashlib
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == result["bundle"]["sha256"]
    assert tip in _git(repo, "bundle", "list-heads", str(bundle))
    _git(repo, "bundle", "verify", str(bundle))
    clone = repo.parent / "restore"  # self-contained: restores into an empty repository
    _git(repo.parent, "init", "-q", str(clone))
    _git(clone, "fetch", "-q", str(bundle), f"{result['quarantine-ref']}:refs/heads/restored")
    assert _git(clone, "rev-parse", "restored") == tip


def test_abandon_needs_the_exact_tip_and_still_refuses_dirty_trees(repo, unmerged, state) -> None:
    feature, tip = unmerged
    for wrong in ("0" * 12, tip[:9]):
        with pytest.raises(AudiaGenticError) as raised:
            finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=lambda _r, _b: (),
                            state_root=state, abandon=wrong)
        assert raised.value.code == "CON-WTFIN-008" and feature.is_dir()
    (feature / "one.txt").write_text("edited")
    with pytest.raises(AudiaGenticError) as raised:
        _abandon(repo, state, feature, tip)
    assert raised.value.code == "CON-WTFIN-002" and "uncommitted-changes" in raised.value.message
    assert feature.is_dir() and git.branch_exists(repo, "me/wip")


def test_abandon_works_without_the_forge_and_on_a_detached_head(repo, unmerged, state) -> None:
    feature, tip = unmerged
    _git(feature, "checkout", "-q", "--detach")

    def forge_down(_repo, _branch):
        raise forge.forge_error(2, "gh failed")

    result = finisher.finish(repo, str(feature), active_work=IDLE, pull_requests=forge_down, state_root=state,
                             abandon=tip[:12])
    assert not feature.exists() and result["bundle"]["commits"] == 2


def test_abandoning_work_already_on_the_default_branch_still_gets_a_bundle(repo, state) -> None:
    feature = (repo.parent / "same").resolve()
    _git(repo, "worktree", "add", "-q", "-b", "me/same", str(feature), "origin/main")
    tip = _git(feature, "rev-parse", "HEAD")
    result = _abandon(repo, state, feature, tip)
    assert result["bundle"]["commits"] == 0 and Path(result["bundle"]["path"]).is_file() and not feature.exists()


def test_abandon_never_overrides_active_gateway_work(repo, unmerged, state) -> None:
    feature, tip = unmerged
    with pytest.raises(AudiaGenticError) as raised:
        finisher.finish(repo, str(feature), active_work=lambda _p: {"requests": ["r"], "sessions": []},
                        pull_requests=lambda _r, _b: (), state_root=state, abandon=tip[:12])
    assert raised.value.code == "CON-WTFIN-002" and "gateway-active-work" in raised.value.message
    assert feature.is_dir()
