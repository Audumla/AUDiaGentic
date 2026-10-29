"""Scope precedence, discovery, validation and provenance of resolve_settings."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from audiagentic.foundation.config.settings import resolve_settings
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths import project as project_paths


@pytest.fixture
def user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the platformdirs user config dir at a tmp XDG_CONFIG_HOME."""
    xdg = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    return xdg / "audiagentic"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _project(tmp_path: Path, text: str | None = None) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    if text is not None:
        _write(root / ".audiagentic" / "settings.yaml", text)
    return root


def test_vendor_defaults_alone(user_config: Path, tmp_path: Path) -> None:
    resolved = resolve_settings(cwd=tmp_path)
    assert resolved.values == {"schema_version": 1}
    assert resolved.origin("schema_version").scope == "vendor"
    assert resolved.project_root is None


def test_precedence_vendor_user_project_explicit_cli(user_config: Path, tmp_path: Path) -> None:
    _write(user_config / "settings.yaml", "schema_version: 1\nagents:\n  default: user-agent\nproject:\n  id: from-user\n")
    root = _project(tmp_path, "schema_version: 1\nagents:\n  default: project-agent\n")
    explicit = _write(tmp_path / "explicit.yaml", "schema_version: 1\nproject:\n  id: from-explicit\n")

    resolved = resolve_settings(project=root, config_file=explicit)
    assert resolved.get("agents.default") == "project-agent"
    assert resolved.get("project.id") == "from-explicit"
    assert resolved.origin("agents.default").scope == "project"
    assert resolved.origin("agents.default").line == 3
    assert resolved.origin("project.id").scope == "explicit"

    with_cli = resolve_settings(project=root, config_file=explicit, overrides={"agents": {"default": "cli-agent"}})
    assert with_cli.get("agents.default") == "cli-agent"
    assert with_cli.origin("agents.default").scope == "cli"


def test_null_in_a_higher_scope_deletes_with_tombstone(user_config: Path, tmp_path: Path) -> None:
    _write(user_config / "settings.yaml", "schema_version: 1\nagents:\n  default: user-agent\n")
    root = _project(tmp_path, "schema_version: 1\nagents:\n  default: null\n")
    resolved = resolve_settings(project=root)
    assert resolved.get("agents.default") is None
    origin = resolved.origin("agents.default")
    assert origin.deleted and origin.scope == "project"


def test_explicit_flag_beats_environment(user_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from_env = _write(tmp_path / "env.yaml", "schema_version: 1\nproject:\n  id: env\n")
    from_flag = _write(tmp_path / "flag.yaml", "schema_version: 1\nproject:\n  id: flag\n")
    monkeypatch.setenv("AUDIAGENTIC_CONFIG", str(from_env))
    assert resolve_settings(cwd=tmp_path).get("project.id") == "env"
    assert resolve_settings(cwd=tmp_path, config_file=from_flag).get("project.id") == "flag"


def test_missing_explicit_inputs_fail(user_config: Path, tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        resolve_settings(cwd=tmp_path, config_file=tmp_path / "nope.yaml")
    assert raised.value.code == "CFG-SET-006"
    with pytest.raises(AudiaGenticError) as raised:
        resolve_settings(project=tmp_path / "no-such-dir")
    assert raised.value.code == "CFG-SET-005"


def test_fragment_errors_point_at_the_file_and_line(user_config: Path, tmp_path: Path) -> None:
    root = _project(tmp_path, "schema_version: 1\nagents:\n  defualt: x\n")
    with pytest.raises(AudiaGenticError) as raised:
        resolve_settings(project=root)
    error = raised.value
    assert error.code == "CFG-SET-004"
    assert error.details["file"].endswith(".audiagentic/settings.yaml")
    assert (error.details["line"], error.details["pointer"]) == (3, "/agents")


@pytest.mark.parametrize(
    "text",
    [
        "agents:\n  default: x\n",            # every file declares schema_version
        "schema_version: 2\n",                 # unknown schema version
        "schema_version: 1\nbogus_section: {}\n",  # sections not yet implemented are rejected
        "schema_version: 1\nproject:\n  id: has spaces\n",
    ],
)
def test_invalid_fragments_are_rejected(user_config: Path, tmp_path: Path, text: str) -> None:
    root = _project(tmp_path, text)
    with pytest.raises(AudiaGenticError) as raised:
        resolve_settings(project=root)
    assert raised.value.code == "CFG-SET-004"


def test_collect_returns_every_issue(user_config: Path, tmp_path: Path) -> None:
    _write(user_config / "settings.yaml", "schema_version: 1\nbogus: 1\n")
    root = _project(tmp_path, "schema_version: 1\nagents:\n  defualt: x\n")
    resolved = resolve_settings(project=root, collect=True)
    assert len(resolved.issues) == 2
    assert {Path(issue.file).name for issue in resolved.issues} == {"settings.yaml"}


def test_project_discovery_walks_up_without_git(user_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path, "schema_version: 1\nproject:\n  id: walked\n")
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.setattr(project_paths.shutil, "which", lambda name: None)
    resolved = resolve_settings(cwd=nested)
    assert resolved.project_root == root.resolve()
    assert resolved.get("project.id") == "walked"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_worktree_reads_its_own_checkout(user_config: Path, tmp_path: Path) -> None:
    main = tmp_path / "main"
    main.mkdir()

    def git(*args: str, cwd: Path = main) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                       capture_output=True)

    git("init", "-q", "-b", "main")
    _write(main / ".audiagentic" / "settings.yaml", "schema_version: 1\nagents:\n  default: on-main\n")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    worktree = tmp_path / "wt-feature"
    git("worktree", "add", "-q", "-b", "feature", str(worktree))
    _write(worktree / ".audiagentic" / "settings.yaml", "schema_version: 1\nagents:\n  default: on-feature\n")

    (worktree / "sub").mkdir()
    from_worktree = resolve_settings(cwd=worktree / "sub")
    assert from_worktree.project_root == worktree.resolve()
    assert from_worktree.get("agents.default") == "on-feature"
    assert resolve_settings(cwd=main).get("agents.default") == "on-main"


def test_resolution_is_read_only(user_config: Path, tmp_path: Path) -> None:
    before = sorted(path for path in tmp_path.rglob("*"))
    resolve_settings(cwd=tmp_path)
    assert sorted(path for path in tmp_path.rglob("*")) == before
    assert not user_config.exists()


def test_sections_are_contributed_by_components(user_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Foundation owns only the envelope; each section comes from its component."""
    from audiagentic.foundation.config.settings import settings_schema
    from audiagentic.foundation.paths.names import get_package_components_config_dir

    shipped = settings_schema()["properties"]
    assert set(shipped) >= {"schema_version", "project", "agents"}

    extra = tmp_path / "components"
    _write(extra / "demo" / "settings" / "demo.schema.json",
           '{"type": "object", "additionalProperties": false, "properties": {"flag": {"type": "boolean"}}}')
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", f"{get_package_components_config_dir()},{extra}")
    root = _project(tmp_path, "schema_version: 1\ndemo:\n  flag: true\n")
    assert resolve_settings(project=root).get("demo.flag") is True

    _write(extra / "other" / "settings" / "agents.schema.json", '{"type": "object"}')
    with pytest.raises(AudiaGenticError) as raised:
        resolve_settings(project=root)
    assert raised.value.code == "CFG-SET-007"
