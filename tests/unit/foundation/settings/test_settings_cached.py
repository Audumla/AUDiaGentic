"""resolve_settings_cached: hot-path memoization that never serves stale settings."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.config import settings
from audiagentic.foundation.config.settings import resolve_settings_cached
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"schema_version: 1\n{text}", encoding="utf-8")


def test_unchanged_files_resolve_once(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    real = settings.resolve_settings
    monkeypatch.setattr(settings, "resolve_settings", lambda **kw: calls.append(kw) or real(**kw))
    _write(project / ".audiagentic" / "settings.yaml", "project: {id: one}\n")
    first = resolve_settings_cached(project)
    assert resolve_settings_cached(project) is first
    assert len(calls) == 1


def test_an_edit_to_any_scope_applies_on_the_next_call(project: Path, tmp_path: Path) -> None:
    project_file = project / ".audiagentic" / "settings.yaml"
    user_file = tmp_path / "xdg" / "audiagentic" / "settings.yaml"
    _write(project_file, "project: {id: one}\n")
    assert resolve_settings_cached(project).get("project.id") == "one"
    _write(project_file, "project: {id: two-longer}\n")  # same mtime tick is possible; size differs
    assert resolve_settings_cached(project).get("project.id") == "two-longer"
    _write(user_file, "gateway: {port: 18411}\n")
    assert resolve_settings_cached(project).get("gateway.port") == 18411


def test_different_projects_do_not_share_results(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    _write(project / ".audiagentic" / "settings.yaml", "project: {id: aaa}\n")
    _write(other / ".audiagentic" / "settings.yaml", "project: {id: bbb}\n")
    assert resolve_settings_cached(project).get("project.id") == "aaa"
    assert resolve_settings_cached(other).get("project.id") == "bbb"


def test_invalid_settings_raise_every_time_and_recover_when_fixed(project: Path) -> None:
    path = project / ".audiagentic" / "settings.yaml"
    _write(path, "bogus: 1\n")
    for _ in range(2):
        with pytest.raises(AudiaGenticError):
            resolve_settings_cached(project)
    _write(path, "project: {id: fixed-id}\n")
    assert resolve_settings_cached(project).get("project.id") == "fixed-id"
