"""`audiagentic config set`: key/value parsing and the end-to-end command."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.commands.settings import build_patch
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.launcher import main


def test_build_patch_nests_dotted_keys_and_types_values() -> None:
    patch = build_patch(
        ["providers.pi.enabled=false", "agents.default=reviewer", 'project.id="123"', "x.list=[1, 2]", "n=7"],
        ["providers.claude.enabled"],
    )
    assert patch == {
        "providers": {"pi": {"enabled": False}, "claude": {"enabled": None}},
        "agents": {"default": "reviewer"},
        "project": {"id": "123"},
        "x": {"list": [1, 2]},
        "n": 7,
    }


def test_an_escaped_dot_stays_inside_one_key() -> None:
    assert build_patch([r"a\.b.c=1"], []) == {"a.b": {"c": 1}}


@pytest.mark.parametrize(
    "assignments, unsets",
    [([], []), (["novalue"], []), (["a="], ["a"]), (["a=1", "a.b=2"], []), (["=1"], []), (["a..b=1"], []),
     (["a={bad"], []), (["a=.inf"], [])],
)
def test_bad_input_is_rejected(assignments: list[str], unsets: list[str]) -> None:
    with pytest.raises(AudiaGenticError) as caught:
        build_patch(assignments, unsets)
    assert caught.value.code == "CFG-SET-013"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


def test_set_writes_the_project_file_and_reports_json(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--project", str(project), "config", "set", "providers.pi.enabled=false", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["written"] and report["keys"] == ["providers.pi.enabled"]
    assert (project / ".audiagentic" / "settings.yaml").read_text(encoding="utf-8").endswith("    enabled: false\n")
    assert main(["--project", str(project), "config", "show", "providers.pi.enabled"]) == 0


def test_set_reports_a_key_overridden_by_a_higher_scope(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("schema_version: 1\nproviders:\n  pi:\n    enabled: true\n", encoding="utf-8")
    code = main(["--project", str(project), "config", "set", "providers.pi.enabled=false",
                 "--config", str(explicit), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["shadowed"][0]["key"] == "providers.pi.enabled"


def test_set_dry_run_and_invalid_values_exit_without_writing(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--project", str(project), "config", "set", "providers.pi.enabled=false", "--dry-run"]) == 0
    assert "would change" in capsys.readouterr().out
    assert not (project / ".audiagentic" / "settings.yaml").exists()
    assert main(["--project", str(project), "config", "set", "providers.pi.enabled=maybe"]) == 2
    assert "CFG-SET-004" in capsys.readouterr().out
    assert main(["--project", str(project), "config", "set", "home=/srv/x"]) == 2
    assert "CFG-SET-009" in capsys.readouterr().out
