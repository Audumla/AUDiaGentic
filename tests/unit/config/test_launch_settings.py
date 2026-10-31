"""The launch switches and the locale are settings; the removed environment variables are not read."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.commands import launch
from audiagentic.components.session import session_api
from audiagentic.foundation.config.launch_settings import launch_setting, locale_setting


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    for name in ("AUDIAGENTIC_STARTUP_STATUS", "AUDIAGENTIC_AUTO_UPDATE_ENABLED", "AUDIAGENTIC_LOCALE"):
        monkeypatch.setenv(name, "0" if name != "AUDIAGENTIC_LOCALE" else "fr")


def _project(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".audiagentic").mkdir()
    (root / ".audiagentic" / "settings.yaml").write_text("schema_version: 1\n" + text, encoding="utf-8")
    return root


def test_defaults_apply_and_the_removed_variables_are_ignored() -> None:
    assert launch_setting("status") is True
    assert launch_setting("auto_update") is True
    assert launch_setting("reconcile_providers") == "auto"
    assert locale_setting() == "en"


def test_project_settings_set_the_switches(tmp_path: Path) -> None:
    root = _project(tmp_path, "launch:\n  status: false\n  auto_update: false\nlocale: de\n")
    assert launch_setting("status", root) is False
    assert launch_setting("auto_update", root) is False
    assert locale_setting(root) == "de"


def test_unreadable_settings_fall_back_to_the_defaults(tmp_path: Path) -> None:
    root = _project(tmp_path, "launch:\n  status: maybe\n")
    assert launch_setting("status", root) is True


def test_startup_status_follows_the_setting(capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch) -> None:
    launch._status("hello")
    assert "hello" in capsys.readouterr().err
    user = tmp_path / "xdg-config" / "audiagentic" / "settings.yaml"
    user.parent.mkdir(parents=True)
    user.write_text("schema_version: 1\nlaunch:\n  status: false\n", encoding="utf-8")
    launch._status("hidden")
    assert capsys.readouterr().err == ""


def test_set_auto_update_persists_to_the_user_settings(tmp_path: Path) -> None:
    result = session_api.set_auto_update(False)
    assert result["ok"] is True and Path(result["file"]).is_file()
    assert launch_setting("auto_update") is False
    session_api.set_auto_update(True)
    assert launch_setting("auto_update") is True
