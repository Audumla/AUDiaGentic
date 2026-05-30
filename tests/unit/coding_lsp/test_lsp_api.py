from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from audiagentic.components.optional.coding_lsp import lsp_api
from audiagentic.components.optional.coding_lsp.lsp_lifecycle import ServerConfig


def test_resolve_project_root_prefers_repo_root_for_nested_file(tmp_path: Path) -> None:
    (tmp_path / ".audiagentic").mkdir()
    nested = tmp_path / "src" / "pkg" / "mod.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("x = 1\n", encoding="utf-8")
    assert lsp_api.resolve_project_root(nested) == tmp_path


def test_definition_uses_repo_root_and_correct_language_for_explicit_config(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    nested = tmp_path / "src" / "pkg" / "mod.rs"
    nested.parent.mkdir(parents=True)
    nested.write_text("fn main() {}\n", encoding="utf-8")

    rust_server = ServerConfig(command=["rust-analyzer"], file_extensions=[".rs"], label="rust")
    monkeypatch.setattr(lsp_api, "discover_servers", lambda project_root: {"rust": rust_server})

    mock_session = MagicMock()
    mock_session.definition.return_value = [{"uri": "file:///def.rs"}]
    captured: dict[str, object] = {}

    def _fake_get_or_create(project_root, language, server):
        captured["project_root"] = project_root
        captured["language"] = language
        captured["server"] = server
        return mock_session

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)

    result = lsp_api.definition(str(nested), "1:1")

    assert result == [{"uri": "file:///def.rs"}]
    assert captured["project_root"] == tmp_path
    assert captured["language"] == "rust"
    assert captured["server"] is rust_server
    mock_session.did_open.assert_called_once()


def test_diagnostics_uses_session_manager_public_api(monkeypatch) -> None:
    called: dict[str, object] = {}

    def _fake_diagnostics(project_root, *, min_severity=4, limit=0):
        called["project_root"] = project_root
        called["min_severity"] = min_severity
        called["limit"] = limit
        return {"file:///tmp/test.py": []}

    monkeypatch.setattr(lsp_api._session_manager, "diagnostics", _fake_diagnostics)

    result = lsp_api.diagnostics(".", min_severity=2, limit=10)

    assert result == {"file:///tmp/test.py": []}
    assert called["min_severity"] == 2
    assert called["limit"] == 10
