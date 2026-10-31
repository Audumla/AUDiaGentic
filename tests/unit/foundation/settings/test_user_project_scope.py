"""The user-project scope: one person's untracked overrides for one project, between project and explicit."""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from audiagentic.foundation.config.settings import (
    resolve_settings,
    scope_sources,
    user_project_settings_path,
)
from audiagentic.foundation.config.writer import write_settings_patch
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)


def _project(root: Path, project_id: str | None = "demo", text: str = "") -> Path:
    (root / ".git").mkdir(parents=True)
    (root / ".audiagentic").mkdir()
    header = f"project:\n  id: {project_id}\n" if project_id else ""
    (root / ".audiagentic" / "settings.yaml").write_text("schema_version: 1\n" + header + text, encoding="utf-8")
    return root


def _file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema_version: 1\n" + text, encoding="utf-8")
    return path


def test_the_scope_sits_between_project_and_explicit(tmp_path: Path) -> None:
    root = _project(tmp_path / "repo")
    scopes = [s.scope for s in scope_sources(project_root=root, config_file=_file(tmp_path / "x.yaml", ""))]
    assert scopes == ["vendor", "user", "project", "user-project", "explicit"]


def test_precedence_user_then_project_then_user_project_then_explicit(tmp_path: Path) -> None:
    root = _project(tmp_path / "repo", text="agents:\n  default: from-project\nlaunch:\n  status: false\n")
    _file(tmp_path / "xdg" / "audiagentic" / "settings.yaml", "agents:\n  default: from-user\nlocale: de\n")
    _file(user_project_settings_path(root), "agents:\n  default: from-user-project\n")
    resolved = resolve_settings(project=root)
    assert resolved.get("agents.default") == "from-user-project"
    assert resolved.origin("agents.default").scope == "user-project"
    assert resolved.get("launch.status") is False and resolved.origin("launch.status").scope == "project"
    assert resolved.get("locale") == "de"

    explicit = _file(tmp_path / "explicit.yaml", "agents:\n  default: from-explicit\n")
    assert resolve_settings(project=root, config_file=explicit).get("agents.default") == "from-explicit"


def test_the_file_is_named_by_the_project_identity_not_the_directory(tmp_path: Path) -> None:
    first = _project(tmp_path / "one" / "checkout", project_id="shared")
    second = _project(tmp_path / "two" / "other-name", project_id="shared")
    assert user_project_settings_path(first) == user_project_settings_path(second)
    assert user_project_settings_path(first).name == "shared.yaml"
    _file(user_project_settings_path(first), "locale: fr\n")
    assert resolve_settings(project=second).get("locale") == "fr"


def test_other_projects_do_not_see_it(tmp_path: Path) -> None:
    mine = _project(tmp_path / "mine", project_id="mine")
    theirs = _project(tmp_path / "theirs", project_id="theirs")
    _file(user_project_settings_path(mine), "locale: fr\n")
    assert resolve_settings(project=mine).get("locale") == "fr"
    assert resolve_settings(project=theirs).get("locale", "unset") in ("unset", "en")


def test_identity_falls_back_to_the_git_repository_name(tmp_path: Path) -> None:
    root = _project(tmp_path / "work" / "checkout", project_id=None)
    (root / ".git" / "config").write_text('[remote "origin"]\n\turl = https://example.invalid/acme/widgets.git\n', encoding="utf-8")
    assert user_project_settings_path(root).name == "widgets.yaml"


def test_a_user_project_value_is_reported_by_origin_and_never_touches_tracked_files(tmp_path: Path) -> None:
    root = _project(tmp_path / "repo", text="launch:\n  status: true\n")
    tracked = (root / ".audiagentic" / "settings.yaml").read_bytes()
    write_settings_patch("user-project", {"launch": {"status": False}}, project_root=root)
    resolved = resolve_settings(project=root)
    assert resolved.get("launch.status") is False
    assert resolved.origin("launch.status").scope == "user-project"
    assert (root / ".audiagentic" / "settings.yaml").read_bytes() == tracked


def test_the_written_file_is_private(tmp_path: Path) -> None:
    root = _project(tmp_path / "repo")
    result = write_settings_patch("user-project", {"locale": "fr"}, project_root=root)
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert result.path == user_project_settings_path(root)


def test_machine_sections_cannot_be_set_in_the_scope(tmp_path: Path) -> None:
    root = _project(tmp_path / "repo")
    with pytest.raises(AudiaGenticError) as caught:
        write_settings_patch("user-project", {"gateway": {"port": 4000}}, project_root=root)
    assert "not read from this scope" in caught.value.message


def test_writing_needs_a_project(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError):
        write_settings_patch("user-project", {"locale": "fr"}, project_root=None)
