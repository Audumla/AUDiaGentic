"""CFG04: stable project identity and tracked project settings shared by worktrees."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.project.doctor_checks import check_identity
from audiagentic.components.project.project_api import context, project_id
from audiagentic.foundation.config.settings import resolve_settings
from audiagentic.foundation.lifecycle.doctor import OK, WARN, DoctorContext


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "safe.directory=*", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def _repo(path: Path, *remotes: tuple[str, str]) -> Path:
    (path / ".git").mkdir(parents=True)
    config = "".join(f'[remote "{name}"]\n\turl = {url}\n' for name, url in remotes)
    (path / ".git" / "config").write_text(config, encoding="utf-8")
    return path


def _settings(root: Path, text: str) -> None:
    (root / ".audiagentic").mkdir(exist_ok=True)
    (root / ".audiagentic" / "settings.yaml").write_text(f"schema_version: 1\n{text}", encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_fresh_worktree_resolves_the_same_id_and_settings(tmp_path: Path) -> None:
    main = tmp_path / "checkout"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _settings(main, "project:\n  id: shared-project\n")
    _git(main, "add", ".audiagentic/settings.yaml")
    _git(main, "commit", "-q", "-m", "settings")
    worktree = tmp_path / "elsewhere" / "wt-feature"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(worktree))

    assert project_id(main) == project_id(worktree) == ("shared-project", "settings")
    assert resolve_settings(project=worktree).origin("project.id").file == str(
        worktree / ".audiagentic" / "settings.yaml"
    )


def test_git_remote_name_is_shared_by_worktrees_and_path_safe(tmp_path: Path) -> None:
    main = _repo(tmp_path / "local-dir", ("origin", "https://user:secret@example.com/org/Repo.Name.git"))
    git_dir = main / ".git" / "worktrees" / "wt"
    git_dir.mkdir(parents=True)
    (git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")

    assert project_id(main) == project_id(worktree) == ("Repo.Name", "git-remote")


def test_fallbacks_are_normalized_and_provisional(tmp_path: Path) -> None:
    assert project_id(_repo(tmp_path / "My Project!")) == ("My-Project", "main-checkout")
    plain = tmp_path / ".hidden name"
    plain.mkdir()
    assert project_id(plain) == ("hidden-name", "folder")


def test_declared_id_and_name_win_over_git(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo", ("origin", "git@example.com:org/remote-name.git"))
    assert project_id(root) == ("remote-name", "git-remote")
    _settings(root, "project:\n  id: declared\n  name: Display Name\n")
    assert project_id(root) == ("declared", "settings")
    assert context(root)["id"] == "declared"
    assert context(root)["name"] == "Display Name"


def test_doctor_reports_provisional_and_ambiguous_identity(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    [result] = check_identity(DoctorContext(root))
    assert result.status == WARN and "project.id" in result.fix

    root = _repo(tmp_path / "forked", ("origin", "https://example.com/a/one.git"),
                 ("upstream", "https://example.com/b/two.git"))
    [result] = check_identity(DoctorContext(root))
    assert result.status == WARN and "origin=one" in result.message and "upstream=two" in result.message

    _settings(root, "project:\n  id: chosen\n")
    [result] = check_identity(DoctorContext(root))
    assert result.status == OK and "'chosen' (settings)" in result.message


def test_provider_project_name_follows_the_declared_id(tmp_path: Path) -> None:
    from audiagentic.components.project.project_api import resolve_project_name

    root = _repo(tmp_path / "somedir")
    assert resolve_project_name(root) == "somedir"  # directory name: provisional
    _settings(root, "project:\n  id: declared-id\n")
    assert resolve_project_name(root) == "declared-id"
    assert resolve_project_name(root, workspace_name="Label") == "declared-id"  # a host label is only a fallback
    _settings(root, "project:\n  id: declared-id\n  name: Explicit Name\n")
    assert resolve_project_name(root) == "Explicit Name"  # an explicit display name still wins
