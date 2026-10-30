"""DW01 slice 4c: push, open or reuse the pull request, request auto-merge; convergent on rerun."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.project.worktrees import merge, merge_plan, publish
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import forge

IDLE = lambda _path: {"requests": [], "sessions": []}  # noqa: E731
ME = forge.RepositoryIdentity("Acme/Widget", "main", True)
TITLE = "feat(thing): add the thing"


def _git(cwd: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xstate"))
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
    monkeypatch.setattr(merge_plan.git, "remote_url",
                        lambda repo, remote="origin", *, push=False: "https://github.com/acme/widget.git")
    feature = (tmp_path / "feature").resolve()
    _git(main, "worktree", "add", "-q", "-b", "me/feature", str(feature), "origin/main")
    (feature / "f.txt").write_text("f\n")
    _git(feature, "add", "f.txt")
    _git(feature, "commit", "-q", "-m", "feature")
    return {"repo": main.resolve(), "feature": feature, "bare": bare, "state": tmp_path / "state", "tmp": tmp_path,
            "tip": _git(feature, "rev-parse", "HEAD")}


class FakeForge:
    """Just enough of a forge: pull requests by number, with the calls recorded."""

    def __init__(self, world, *, existing=None, accept_auto_merge=True, head_override=None, hide_created=False):
        self.world, self.calls, self.prs = world, [], {}
        self.accept, self.head_override, self.hide_created = accept_auto_merge, head_override, hide_created
        if existing:
            self.prs[existing.number] = existing

    def find(self, _repo, _branch):
        return tuple(pr for pr in self.prs.values() if not (self.hide_created and pr.number >= 100))

    def create(self, _repo, *, head, base, title, body, repository=None):
        self.calls.append(("create", head, base, title, body, repository))
        number = 100 + len(self.prs)
        self.prs[number] = forge.PullRequest(number, "OPEN", base, head, self.head_override or self.world["tip"], None,
                                             False, f"https://example.invalid/{number}", title=title)
        return f"https://example.invalid/{number}"

    def retitle(self, _repo, number, title, *, repository=None):
        self.calls.append(("retitle", number, title, repository))
        self.prs[number] = _replace(self.prs[number], title=title)

    def auto_merge(self, _repo, number, *, head_sha, repository=None):
        self.calls.append(("auto-merge", number, head_sha, repository))
        if self.accept:
            self.prs[number] = _replace(self.prs[number], auto_merge=True)

    def read(self, _repo, number, *, repository=None):
        return self.prs[number]


def _replace(pr: forge.PullRequest, **changes) -> forge.PullRequest:
    values = {**pr.__dict__, **changes}
    return forge.PullRequest(**values)


def _open_pr(world, **kwargs) -> forge.PullRequest:
    base = dict(number=7, state="OPEN", base="main", head_branch="me/feature", head_sha=world["tip"], merge_commit=None,
                cross_repository=False, url="https://example.invalid/7", title=TITLE)
    return forge.PullRequest(**{**base, **kwargs})


def _run(world, fake, *, title=TITLE, body=None, **kwargs):
    return merge.merge(world["repo"], world["feature"], title=title, body=body, active_work=IDLE,
                       state_root=world["state"], find=fake.find, identity=lambda _r: ME, create=fake.create,
                       retitle=fake.retitle, auto_merge=fake.auto_merge, read=fake.read, **kwargs)


def _remote_tip(world) -> str | None:
    try:
        return _git(world["bare"], "rev-parse", "refs/heads/me/feature")
    except subprocess.CalledProcessError:
        return None


def _calls(fake) -> list[str]:
    return [call[0] for call in fake.calls]


def test_fresh_worktree_is_pushed_opened_and_set_to_auto_merge(world) -> None:
    fake = FakeForge(world)
    result = _run(world, fake, body="Why this change.")
    assert _remote_tip(world) == world["tip"] and result["pushed"] and result["created"]
    assert _calls(fake) == ["create", "auto-merge"] and fake.calls[0][1:4] == ("me/feature", "main", TITLE)
    assert result["auto-merge"] is True and result["pr"] == 100 and result["behind"] is False
    receipts = [json.loads(p.read_text()) for p in (world["state"] / "worktrees" / "receipts").rglob("*.json")]
    merges = [receipt for receipt in receipts if receipt.get("kind") == "merge"]  # the push attempt has its own receipt
    assert len(merges) == 1 and merges[0]["phase"] == "AUTO_MERGE_REQUESTED"


def test_rerun_converges_without_repeating_anything(world) -> None:
    fake = FakeForge(world)
    _run(world, fake)
    fake.calls.clear()
    second = _run(world, fake)
    assert fake.calls == [] and second["pushed"] is False and second["created"] is False and second["pr"] == 100


def test_existing_pull_request_is_reused_and_retitled_only_when_different(world) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")  # already published
    fake = FakeForge(world, existing=_open_pr(world, title="feat(old): old title"))
    result = _run(world, fake)
    assert result["pr"] == 7 and result["pushed"] is False and _calls(fake) == ["retitle", "auto-merge"]
    fake = FakeForge(world, existing=_open_pr(world, auto_merge=True))
    _run(world, fake)
    assert fake.calls == []


def test_a_pull_request_whose_head_is_not_the_pushed_commit_gets_no_auto_merge(world) -> None:
    fake = FakeForge(world, head_override="0" * 40)
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake)
    assert raised.value.code == "CON-WTMERGE-005" and "auto-merge" not in _calls(fake)


def test_a_forge_that_refuses_auto_merge_is_reported(world) -> None:
    fake = FakeForge(world, accept_auto_merge=False)
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake)
    assert raised.value.code == "CON-WTMERGE-006" and _remote_tip(world) == world["tip"]  # push and PR are kept


def test_a_created_pull_request_that_cannot_be_found_stops_before_auto_merge(world) -> None:
    fake = FakeForge(world, hide_created=True)
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake)
    assert raised.value.code == "CON-WTMERGE-004" and "auto-merge" not in _calls(fake)


def test_blockers_stop_everything_before_any_push_or_pull_request(world) -> None:
    fake = FakeForge(world)
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake, title=None)
    assert raised.value.code == "CON-WTMERGE-003" and "title-required" in raised.value.message
    assert fake.calls == [] and _remote_tip(world) is None
    (world["feature"] / "dirty.txt").write_text("x")
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake)
    assert "uncommitted-changes" in raised.value.message and _remote_tip(world) is None


def test_two_open_pull_requests_are_never_guessed_between(world) -> None:
    fake = FakeForge(world, existing=_open_pr(world, number=1))
    fake.prs[2] = _open_pr(world, number=2)
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake)
    assert raised.value.code == "CON-WTMERGE-003" and "pr-ambiguous" in raised.value.message and fake.calls == []


def test_the_project_trailer_is_appended_to_the_body(world) -> None:
    target = world["repo"] / ".audiagentic" / "settings.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("schema_version: 1\nworktrees:\n  pr-trailer: 'Generated with the tool.'\n")
    fake = FakeForge(world)
    _run(world, fake, body="Why.")
    assert fake.calls[0][4] == "Why.\n\nGenerated with the tool."


def test_behind_is_reported_not_fixed(world) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    fake = FakeForge(world, existing=_open_pr(world, auto_merge=True, merge_state="BEHIND"))
    result = _run(world, fake)
    assert result["behind"] is True and fake.calls == []


def test_the_push_uses_the_checks_and_failures_leave_no_pull_request(world) -> None:
    def failing(*args, **kwargs):
        raise AudiaGenticError(code="CON-WTPUSH-004", kind="conflict", message="check failed")

    fake = FakeForge(world)
    with pytest.raises(AudiaGenticError):
        _run(world, fake, push=failing)
    assert fake.calls == [] and _remote_tip(world) is None
    assert publish.refuse_error  # the real push path is what merge uses by default


def test_forge_calls_are_pinned_to_the_repository_and_the_exact_head(world) -> None:
    fake = FakeForge(world)
    _run(world, fake)
    create, enable = fake.calls
    assert create[5] == "Acme/Widget" and enable == ("auto-merge", 100, world["tip"], "Acme/Widget")


def test_an_already_merged_tip_on_rerun_is_success_not_an_error(world) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    fake = FakeForge(world, existing=_open_pr(world, state="MERGED", merge_commit="a" * 40))
    result = _run(world, fake)
    assert result["already-merged"] is True and fake.calls == []


def test_a_draft_pull_request_is_refused_before_anything_on_it_is_changed(world) -> None:
    _git(world["feature"], "push", "-q", "origin", "me/feature")
    fake = FakeForge(world, existing=_open_pr(world, title="feat(old): old", is_draft=True))
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake)
    assert raised.value.code == "CON-WTMERGE-003" and "pr-draft" in raised.value.message and fake.calls == []


def test_an_oversized_body_is_refused_before_pushing(world) -> None:
    fake = FakeForge(world)
    with pytest.raises(AudiaGenticError) as raised:
        _run(world, fake, body="x" * 20001)
    assert raised.value.code == "CON-WTMERGE-003" and fake.calls == [] and _remote_tip(world) is None


def test_the_real_gh_arguments_are_shell_free_pinned_and_head_bound(monkeypatch, tmp_path) -> None:
    import subprocess

    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs.get("input")))
        return subprocess.CompletedProcess(argv, 0, "https://github.com/acme/widget/pull/5\n", "")

    monkeypatch.setattr(forge.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(forge.subprocess, "run", fake_run)
    url = forge.create_pull_request(tmp_path, head="me/feature", base="main", title="feat: x", body="-- starts with dashes",
                                    repository="Acme/Widget")
    forge.enable_auto_merge(tmp_path, 5, head_sha="a" * 40, repository="Acme/Widget")
    forge.set_pull_request_title(tmp_path, 5, "feat: y", repository="Acme/Widget")
    create, enable, edit = seen
    assert url.endswith("/pull/5") and "--repo" in create[0] and "Acme/Widget" in create[0]
    assert create[0][create[0].index("--body-file") + 1] == "-" and create[1] == "-- starts with dashes"
    assert "--body" not in create[0]
    assert enable[0][enable[0].index("--match-head-commit") + 1] == "a" * 40 and "--auto" in enable[0]
    assert "--repo" in edit[0] and all(isinstance(part, str) for part in create[0] + enable[0] + edit[0])
