"""Unit tests for project_files.read_project_file discovery behavior."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.project.project_files import read_project_file
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _make_project(tmp_path: Path) -> Path:
    audia_dir = tmp_path / ".audiagentic" / "config"
    audia_dir.mkdir(parents=True)
    (audia_dir / "project.yaml").write_text("id: demo\n", encoding="utf-8")
    return tmp_path


def test_read_project_file_reads_existing_file(tmp_path):
    root = _make_project(tmp_path)
    result = read_project_file(root, ".audiagentic/config/project.yaml")
    assert "id: demo" in result["content"]


def test_read_project_file_dot_lists_root(tmp_path):
    root = _make_project(tmp_path)
    result = read_project_file(root, ".")
    assert result["is_dir"] is True
    assert "config/" in result["entries"]


def test_read_project_file_empty_string_lists_root(tmp_path):
    root = _make_project(tmp_path)
    result = read_project_file(root, "")
    assert result["is_dir"] is True
    assert "config/" in result["entries"]


def test_read_project_file_directory_path_lists_contents(tmp_path):
    root = _make_project(tmp_path)
    result = read_project_file(root, ".audiagentic/config")
    assert result["is_dir"] is True
    assert "project.yaml" in result["entries"]


def test_read_project_file_rejects_path_outside_audiagentic(tmp_path):
    root = _make_project(tmp_path)
    with pytest.raises(AudiaGenticError) as exc_info:
        read_project_file(root, "src/audiagentic/__init__.py")
    assert exc_info.value.code == "VAL-PROJFILE-001"
    assert ".audiagentic/" in str(exc_info.value)


def test_read_project_file_missing_path_still_errors(tmp_path):
    root = _make_project(tmp_path)
    with pytest.raises(AudiaGenticError) as exc_info:
        read_project_file(root, ".audiagentic/config/missing.yaml")
    assert exc_info.value.code == "RES-PROJFILE-001"
