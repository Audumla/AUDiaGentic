"""config show / validate / paths: read-only, no app graph, stable exit codes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.launcher import _main


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import audiagentic.runtime.bootstrap as bootstrap

    def fail(**kwargs):
        raise AssertionError("settings commands must not compose the application graph")

    monkeypatch.setattr(bootstrap, "build_application_graph", fail)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".audiagentic").mkdir()
    (root / ".audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\nagents:\n  default: reviewer\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    return root


def _json(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


def test_show_key_with_origin_json(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["config", "show", "agents.default", "--origin", "--json"]) == 0
    out = _json(capsys)
    assert out["value"] == "reviewer"
    assert out["origin"]["scope"] == "project" and out["origin"]["line"] == 3


def test_show_missing_key_exits_1(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["config", "show", "project.id"]) == 1
    assert "not set" in capsys.readouterr().out


def test_show_all_text(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["config", "show", "--origin"]) == 0
    out = capsys.readouterr().out
    assert 'agents.default = "reviewer"' in out and "project" in out


def test_validate_reports_issues_with_exit_2(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["config", "validate", "--json"]) == 0
    assert _json(capsys)["ok"] is True
    (isolated / ".audiagentic" / "settings.yaml").write_text("schema_version: 1\nbogus: 1\n", encoding="utf-8")
    assert _main(["config", "validate", "--json"]) == 2
    out = _json(capsys)
    assert out["ok"] is False and out["issues"][0]["line"] == 1


def test_invalid_yaml_and_missing_inputs_exit_codes(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (isolated / ".audiagentic" / "settings.yaml").write_text("a: &x 1\n", encoding="utf-8")
    assert _main(["config", "show"]) == 2
    assert "CFG-SET-003" in capsys.readouterr().out
    assert _main(["config", "show", "--config", str(isolated / "missing.yaml")]) == 3
    capsys.readouterr()
    assert _main(["--project", str(isolated / "nowhere"), "config", "show", "--json"]) == 3
    assert _json(capsys)["error-code"] == "CFG-SET-005"


def test_paths_json_lists_scopes_without_creating_anything(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = sorted(isolated.parent.rglob("*"))
    assert _main(["config", "paths", "--json"]) == 0
    out = _json(capsys)
    scopes = {row["scope"]: row for row in out["paths"] if row["kind"] == "settings"}
    assert scopes["project"]["present"] is True
    assert scopes["user"]["present"] is False
    assert sorted(isolated.parent.rglob("*")) == before
