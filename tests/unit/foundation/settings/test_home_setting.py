"""CFG08: the home directory can be chosen in the machine-scope settings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.foundation.config.settings import resolve_settings
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.names import home_directory, home_source


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No environment home, an isolated user config directory, and a git project as cwd."""
    monkeypatch.delenv("AUDIAGENTIC_HOME", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    monkeypatch.chdir(project)
    return project


def _user_settings(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "xdg" / "audiagentic" / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"schema_version: 1\n{text}", encoding="utf-8")
    return path


def test_the_default_is_the_dot_directory_in_the_user_home(machine: Path, tmp_path: Path) -> None:
    assert home_source() == (tmp_path / "userhome" / ".audiagentic", "default")


def test_the_user_setting_chooses_the_home(machine: Path, tmp_path: Path) -> None:
    _user_settings(tmp_path, f"home: {tmp_path / 'shared-home'}\n")
    assert home_source() == (tmp_path / "shared-home", "settings")
    assert home_directory() == tmp_path / "shared-home"


def test_the_environment_wins_over_the_setting(machine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _user_settings(tmp_path, f"home: {tmp_path / 'shared-home'}\n")
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "env-home"))
    assert home_source() == (tmp_path / "env-home", "environment")


def test_a_leading_tilde_expands(machine: Path, tmp_path: Path) -> None:
    _user_settings(tmp_path, "home: ~/shared\n")
    assert home_directory() == tmp_path / "userhome" / "shared"


def test_a_projects_own_settings_never_choose_the_home(machine: Path, tmp_path: Path) -> None:
    (machine / ".audiagentic").mkdir()
    (machine / ".audiagentic" / "settings.yaml").write_text(
        f"schema_version: 1\nhome: {tmp_path / 'project-chosen'}\n", encoding="utf-8",
    )
    assert resolve_settings().get("home") == str(tmp_path / "project-chosen")  # valid configuration...
    assert home_source()[1] == "default"  # ...that the machine-wide home never reads


def test_an_explicit_settings_file_can_choose_the_home(machine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    explicit = tmp_path / "server.yaml"
    explicit.write_text(f"schema_version: 1\nhome: {tmp_path / 'server-home'}\n", encoding="utf-8")
    assert home_source(explicit) == (tmp_path / "server-home", "settings")
    monkeypatch.setenv("AUDIAGENTIC_CONFIG", str(explicit))
    assert home_source() == (tmp_path / "server-home", "settings")


@pytest.mark.parametrize("value", ["relative/path", "''", "5", "[a, b]"])
def test_the_schema_rejects_what_is_not_an_absolute_path(machine: Path, tmp_path: Path, value: str) -> None:
    _user_settings(tmp_path, f"home: {value}\n")
    with pytest.raises(AudiaGenticError):
        resolve_settings(machine_only=True)


def test_an_invalid_settings_file_raises_instead_of_picking_another_home(machine: Path, tmp_path: Path) -> None:
    _user_settings(tmp_path, "home: [unclosed\n")
    with pytest.raises(AudiaGenticError):
        home_directory()


def test_settings_resolution_does_not_need_the_home(machine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The home reads the settings, so the settings must never read the home (no cycle)."""
    import audiagentic.foundation.paths.names as names

    _user_settings(tmp_path, f"home: {tmp_path / 'shared-home'}\n")
    monkeypatch.setattr(names, "home_directory", lambda: (_ for _ in ()).throw(AssertionError("settings read the home")))
    assert resolve_settings(machine_only=True).get("home") == str(tmp_path / "shared-home")


def test_config_paths_reports_the_home_and_where_it_came_from(
    machine: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from audiagentic.launcher import _main

    _user_settings(tmp_path, f"home: {tmp_path / 'shared-home'}\n")
    assert _main(["config", "paths", "--json"]) == 0
    rows = {row["kind"]: row for row in json.loads(capsys.readouterr().out)["paths"] if row["kind"] != "settings"}
    assert rows["home"]["scope"] == "settings" and rows["home"]["path"] == str(tmp_path / "shared-home")
