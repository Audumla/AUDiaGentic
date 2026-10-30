"""write_settings_patch: comment-preserving, validated, conflict-safe settings writes."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from audiagentic.foundation.config import writer
from audiagentic.foundation.config.settings import resolve_settings, resolve_settings_cached
from audiagentic.foundation.config.writer import BACKUPS_KEPT, write_settings_patch
from audiagentic.foundation.contracts.errors import AudiaGenticError

DOCUMENT = """# project settings
schema_version: 1

providers:
  gpt-auto:   # the browser one
    enabled: auto
  claude:
    enabled: true
# trailing note
agents:
  default: reviewer
"""


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


def _file(project: Path) -> Path:
    return project / ".audiagentic" / "settings.yaml"


def _seed(project: Path, text: str = DOCUMENT) -> Path:
    path = _file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _code(error: pytest.ExceptionInfo[AudiaGenticError]) -> str:
    return error.value.code


def test_a_write_changes_only_the_requested_key_and_keeps_comments(project: Path) -> None:
    path = _seed(project)
    result = write_settings_patch("project", {"providers": {"gpt-auto": {"enabled": False}}}, project_root=project)
    assert (result.changed, result.written, result.keys) == (True, True, ("providers.gpt-auto.enabled",))
    assert path.read_text(encoding="utf-8") == DOCUMENT.replace("enabled: auto", "enabled: false")
    assert resolve_settings(project=project).get("providers.gpt-auto.enabled") is False


def test_a_missing_file_is_created_with_the_schema_version(project: Path) -> None:
    write_settings_patch("project", {"providers": {"pi": {"enabled": True}}}, project_root=project)
    assert _file(project).read_text(encoding="utf-8") == "schema_version: 1\nproviders:\n  pi:\n    enabled: true\n"


def test_deleting_keys_and_adding_sections_keeps_the_rest(project: Path) -> None:
    path = _seed(project)
    write_settings_patch("project", {"providers": {"claude": None}, "project": {"id": "demo"}}, project_root=project)
    text = path.read_text(encoding="utf-8")
    assert "claude" not in text and "# trailing note" in text and "# the browser one" not in text.replace("browser one", "x")
    assert resolve_settings(project=project).get("project.id") == "demo"


def test_a_no_op_writes_nothing_and_makes_no_backup(project: Path) -> None:
    path = _seed(project)
    before = path.stat().st_mtime_ns
    result = write_settings_patch("project", {"providers": {"gpt-auto": {"enabled": "auto"}}}, project_root=project)
    assert (result.changed, result.written, result.backup) == (False, False, None)
    assert path.stat().st_mtime_ns == before


def test_dry_run_reports_the_diff_and_changes_nothing(project: Path) -> None:
    path = _seed(project)
    result = write_settings_patch(
        "project", {"providers": {"gpt-auto": {"enabled": True}}}, project_root=project, dry_run=True,
    )
    assert result.changed and not result.written
    assert "-    enabled: auto" in result.diff and "+    enabled: true" in result.diff
    assert path.read_text(encoding="utf-8") == DOCUMENT


def test_an_invalid_value_is_refused_before_anything_is_written(project: Path) -> None:
    path = _seed(project)
    with pytest.raises(AudiaGenticError) as caught:
        write_settings_patch("project", {"providers": {"gpt-auto": {"enabled": "maybe"}}}, project_root=project)
    assert _code(caught) == "CFG-SET-004"
    assert path.read_text(encoding="utf-8") == DOCUMENT


def test_a_machine_only_section_is_refused_in_the_project_scope(project: Path) -> None:
    with pytest.raises(AudiaGenticError) as caught:
        write_settings_patch("project", {"home": "/srv/audiagentic"}, project_root=project)
    assert _code(caught) == "CFG-SET-009"
    assert not _file(project).exists()
    write_settings_patch("user", {"home": "/srv/audiagentic"})
    assert resolve_settings(project=project).get("home") == "/srv/audiagentic"


@pytest.mark.parametrize("scope", ["vendor", "explicit", "bogus"])
def test_only_user_and_project_scopes_are_writable(project: Path, scope: str) -> None:
    with pytest.raises(AudiaGenticError) as caught:
        write_settings_patch(scope, {"agents": {"default": "x"}}, project_root=project)
    assert _code(caught) == "CFG-SET-008"


def test_a_symlinked_target_or_directory_is_refused(project: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("schema_version: 1\n", encoding="utf-8")
    _file(project).parent.mkdir(parents=True)
    _file(project).symlink_to(elsewhere)
    with pytest.raises(AudiaGenticError) as caught:
        write_settings_patch("project", {"agents": {"default": "x"}}, project_root=project)
    assert _code(caught) == "CFG-SET-010"
    assert elsewhere.read_text(encoding="utf-8") == "schema_version: 1\n"


def test_an_edit_made_while_the_write_is_prepared_is_refused(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _seed(project)
    original = writer.document_issues

    def human_edits_meanwhile(document):
        path.write_text(DOCUMENT + "# added by a person\n", encoding="utf-8")
        return original(document)

    monkeypatch.setattr(writer, "document_issues", human_edits_meanwhile)
    with pytest.raises(AudiaGenticError) as caught:
        write_settings_patch("project", {"agents": {"default": "other"}}, project_root=project)
    assert _code(caught) == "CFG-SET-011"
    assert "# added by a person" in path.read_text(encoding="utf-8")
    assert "other" not in path.read_text(encoding="utf-8")


def test_the_previous_content_is_backed_up_and_backups_are_bounded(project: Path) -> None:
    _seed(project)
    first = write_settings_patch("project", {"agents": {"default": "a0"}}, project_root=project)
    assert first.backup is not None and first.backup.read_text(encoding="utf-8") == DOCUMENT
    assert stat.S_IMODE(first.backup.stat().st_mode) == 0o600
    for number in range(1, BACKUPS_KEPT + 3):
        write_settings_patch("project", {"agents": {"default": f"a{number}"}}, project_root=project)
    assert len(list(first.backup.parent.iterdir())) == BACKUPS_KEPT


def test_file_permissions_are_preserved(project: Path) -> None:
    path = _seed(project)
    path.chmod(0o640)
    write_settings_patch("project", {"agents": {"default": "x"}}, project_root=project)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_the_cached_resolver_sees_each_write_without_a_restart(project: Path) -> None:
    _seed(project)
    assert resolve_settings_cached(project).get("agents.default") == "reviewer"
    for value in ("one", "two", "three"):
        write_settings_patch("project", {"agents": {"default": value}}, project_root=project)
        assert resolve_settings_cached(project).get("agents.default") == value


def test_a_layout_the_editor_cannot_reproduce_exactly_is_refused(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _seed(project)
    monkeypatch.setattr(writer, "patch_text", lambda text, old, patch: text)
    with pytest.raises(AudiaGenticError) as caught:
        write_settings_patch("project", {"agents": {"default": "x"}}, project_root=project)
    assert _code(caught) == "CFG-SET-012"
    assert path.read_text(encoding="utf-8") == DOCUMENT


def test_a_syntactically_invalid_existing_file_is_never_overwritten(project: Path) -> None:
    broken = "providers: [unclosed\n"
    path = _seed(project, broken)
    with pytest.raises(AudiaGenticError):
        write_settings_patch("project", {"agents": {"default": "x"}}, project_root=project)
    assert path.read_text(encoding="utf-8") == broken
    assert os.listdir(path.parent) == ["settings.yaml"]


def test_concurrent_writers_do_not_lose_each_others_keys(project: Path) -> None:
    import threading

    _seed(project)
    errors: list[BaseException] = []

    def write(name: str) -> None:
        try:
            write_settings_patch("project", {"providers": {name: {"enabled": True}}}, project_root=project)
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    names = [f"p{n}" for n in range(8)]
    threads = [threading.Thread(target=write, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    resolved = resolve_settings(project=project)
    assert all(resolved.get(f"providers.{name}.enabled") is True for name in names)
