from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.optional.coding_lsp.config import (
    detect_project_languages,
    discover_language_servers,
    merge_server_configs,
    read_lsp_config,
    resolve_root_uri,
    resolve_server_for_file,
    write_lsp_config,
)
from audiagentic.components.optional.coding_lsp.lsp_lifecycle import ServerConfig


def test_read_lsp_config_missing_file() -> None:
    result = read_lsp_config(Path("/nonexistent/lsp.json"))
    assert result == {}


def test_write_and_read_lsp_config(tmp_path: Path) -> None:
    path = tmp_path / "lsp.json"
    servers = {
        "python": {
            "command": ["pyright-langserver", "--stdio"],
            "fileExtensions": [".py"],
        }
    }
    write_lsp_config(path, servers)
    result = read_lsp_config(path)
    assert "python" in result
    assert result["python"]["command"] == ["pyright-langserver", "--stdio"]


def test_detect_project_languages_python(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").touch()
    detected = detect_project_languages(tmp_path)
    assert "python" in detected


def test_detect_project_languages_typescript(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").touch()
    detected = detect_project_languages(tmp_path)
    assert "typescript" in detected


def test_detect_project_languages_rust(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").touch()
    detected = detect_project_languages(tmp_path)
    assert "rust" in detected


def test_detect_project_languages_none(tmp_path: Path) -> None:
    detected = detect_project_languages(tmp_path)
    assert detected == {}


def test_merge_explicit_wins_over_detected() -> None:
    explicit = {
        "python": {"command": ["custom-pyright"], "fileExtensions": [".py"]}
    }
    detected = {"python": "pyproject.toml", "rust": "Cargo.toml"}
    merged = merge_server_configs(explicit, detected)
    assert "python" in merged
    assert merged["python"].command == ["custom-pyright"]
    assert "rust" in merged


def test_merge_detected_fills_gaps() -> None:
    explicit = {}
    detected = {"python": "pyproject.toml"}
    merged = merge_server_configs(explicit, detected)
    assert "python" in merged
    assert merged["python"].command == ["pyright-langserver", "--stdio"]


def test_resolve_server_for_file_python() -> None:
    servers = {
        "python": ServerConfig(
            command=["pyright-langserver"],
            file_extensions=[".py", ".pyi"],
        )
    }
    result = resolve_server_for_file(Path("src/foo.py"), servers)
    assert result is not None
    assert result.command == ["pyright-langserver"]


def test_resolve_server_for_file_unknown() -> None:
    servers = {
        "python": ServerConfig(
            command=["pyright-langserver"],
            file_extensions=[".py"],
        )
    }
    result = resolve_server_for_file(Path("src/foo.rs"), servers)
    assert result is None


def test_resolve_root_uri() -> None:
    uri = resolve_root_uri(Path(__file__).resolve().parent)
    assert uri.startswith("file://")


def test_discover_language_servers_returns_dict(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").touch()
    result = discover_language_servers(tmp_path)
    assert isinstance(result, dict)
    assert "python" in result
