from __future__ import annotations

from pathlib import Path

from audiagentic.components.optional.coding_lsp.coding_lsp_bootstrap import _active_dependency_ids
from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
    detect_project_languages,
    discover_language_servers,
    load_runtime_servers,
    read_lsp_config,
    resolve_root_uri,
    resolve_server_for_file,
    write_lsp_config,
)
from audiagentic.components.optional.coding_lsp.lsp_lifecycle import ServerConfig


def test_read_lsp_config_missing_file() -> None:
    result = read_lsp_config(Path("/nonexistent/lsp.json"))
    assert result == {}


def test_load_runtime_servers_missing_file() -> None:
    servers, errors, exists = load_runtime_servers(Path("/nonexistent/lsp.json"))
    assert servers == {}
    assert errors == []
    assert exists is False


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


def test_load_runtime_servers_validates_runtime_entries(tmp_path: Path) -> None:
    path = tmp_path / "lsp.json"
    write_lsp_config(path, {
        "python": {
            "command": ["pyright-langserver", "--stdio"],
            "fileExtensions": [".py"],
        }
    })
    servers, errors, exists = load_runtime_servers(path)
    assert exists is True
    assert errors == []
    assert servers["python"].command == ["pyright-langserver", "--stdio"]
    assert servers["python"].file_extensions == [".py"]


def test_load_runtime_servers_invalid_json_fails_gracefully(tmp_path: Path) -> None:
    path = tmp_path / "lsp.json"
    path.write_text("{bad json", encoding="utf-8")
    servers, errors, exists = load_runtime_servers(path)
    assert exists is True
    assert servers == {}
    assert errors


def test_load_runtime_servers_rejects_missing_file_extensions(tmp_path: Path) -> None:
    path = tmp_path / "lsp.json"
    write_lsp_config(path, {
        "python": {
            "command": ["pyright-langserver", "--stdio"],
        }
    })
    servers, errors, exists = load_runtime_servers(path)
    assert exists is True
    assert servers == {}
    assert errors == ["python: file_extensions must be non-empty list[str]"]


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
    assert result == {}


def test_discover_language_servers_uses_only_explicit_runtime_config(tmp_path: Path) -> None:
    lsp_json = tmp_path / ".coding-lsp" / "lsp.json"
    write_lsp_config(lsp_json, {
        "python": {
            "command": ["pyright-langserver", "--stdio"],
            "fileExtensions": [".py"],
        }
    })
    result = discover_language_servers(tmp_path)
    assert "python" in result
    assert isinstance(result["python"], bool)


def test_makefile_does_not_trigger_cpp_detection(tmp_path: Path) -> None:
    (tmp_path / "Makefile").touch()
    detected = detect_project_languages(tmp_path)
    assert "cpp" not in detected, "Makefile alone should not trigger C++ detection"


def test_cmake_triggers_cpp_detection(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").touch()
    detected = detect_project_languages(tmp_path)
    assert "cpp" in detected


def test_active_dependency_ids_reads_from_lsp_json(tmp_path: Path) -> None:
    from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
        CODING_LSP_DIR,
        write_lsp_config,
    )
    lsp_json = tmp_path / CODING_LSP_DIR / "lsp.json"
    write_lsp_config(lsp_json, {"python": {"command": ["pyright-langserver", "--stdio"], "fileExtensions": [".py"]}})
    dep_ids = _active_dependency_ids(tmp_path)
    assert "pyright" in dep_ids
    assert "typescript-language-server" not in dep_ids
    assert "clangd" not in dep_ids


def test_active_dependency_ids_no_lsp_json_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").touch()
    dep_ids = _active_dependency_ids(tmp_path)
    assert dep_ids == [], "No lsp.json means no active deps — lsp.json is the source of truth"


def test_active_dependency_ids_no_project_root_returns_empty() -> None:
    dep_ids = _active_dependency_ids(None)
    assert dep_ids == []


def test_active_dependency_ids_excludes_unconfigured_languages(tmp_path: Path) -> None:
    from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
        CODING_LSP_DIR,
        write_lsp_config,
    )
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "Makefile").touch()
    lsp_json = tmp_path / CODING_LSP_DIR / "lsp.json"
    write_lsp_config(lsp_json, {"python": {"command": ["pyright-langserver", "--stdio"], "fileExtensions": [".py"]}})
    dep_ids = _active_dependency_ids(tmp_path)
    assert "clangd" not in dep_ids, "Only configured languages in lsp.json should appear"
