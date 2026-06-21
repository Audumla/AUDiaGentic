from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from audiagentic.components.optional.coding_lsp import lsp_api, lsp_config_api
from audiagentic.components.optional.coding_lsp.coding_lsp_config import write_lsp_config
from audiagentic.components.optional.coding_lsp.lsp_lifecycle import ServerConfig
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import (
    BindingDescriptor,
    FeatureState,
    ImplementationDescriptor,
    ImplementationState,
)
from audiagentic.foundation.features.state import (
    get_feature_state,
    set_feature_state,
    set_implementation_state,
)


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


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

    assert len(result) == 1
    assert result[0]["uri"] == "file:///def.rs"
    assert "file" in result[0]
    assert "range" in result[0]
    assert "line" in result[0]
    assert "character" in result[0]
    assert captured["project_root"] == tmp_path
    assert captured["language"] == "rust"
    assert captured["server"] is rust_server
    mock_session.sync_document.assert_called_once()


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


def test_config_status_reports_missing_config(tmp_path: Path) -> None:
    (tmp_path / ".audiagentic").mkdir()
    status = lsp_config_api.config_status(str(tmp_path))
    assert status["projection_cache"]["exists"] is False
    assert status["projection_cache"]["valid"] is False
    assert status["implementation"] == "ag-lsp"
    assert status["languages"] == {}


def test_config_status_reports_invalid_config(tmp_path: Path) -> None:
    (tmp_path / ".audiagentic").mkdir()
    lsp_json = tmp_path / ".coding-lsp" / "lsp.json"
    lsp_json.parent.mkdir(parents=True)
    lsp_json.write_text("{bad json", encoding="utf-8")
    status = lsp_config_api.config_status(str(tmp_path))
    assert status["projection_cache"]["exists"] is True
    assert status["projection_cache"]["valid"] is False
    assert status["projection_cache"]["errors"]


def test_config_status_reports_feature_state_and_implementation(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    write_lsp_config(tmp_path / ".coding-lsp" / "lsp.json", {
        "python": {
            "command": ["pyright-langserver", "--stdio"],
            "file_extensions": [".py"],
        },
    })
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="agent-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="agent-lsp.mcp-args",
        )
    )
    lsp_config_api._set_language_feature_enabled(tmp_path, "python", True)
    set_implementation_state(
        tmp_path,
        "coding-lsp",
        "agent-lsp",
        ImplementationState(enabled=True),
    )
    monkeypatch.setattr(lsp_config_api, "detect_missing", lambda probes, ids: [])

    status = lsp_config_api.config_status(str(tmp_path))

    assert status["implementation"] == "agent-lsp"
    assert status["languages"]["python"]["feature_enabled"] is True
    assert status["languages"]["python"]["feature_options"] == {}


def test_list_and_select_implementations(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="ag-lsp", display_name="AG LSP")
    )
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="agent-lsp", display_name="Agent LSP")
    )
    synced: list[Path] = []
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: synced.append(root))

    selected = lsp_config_api.select_implementation(str(tmp_path), "agent-lsp")
    listed = lsp_config_api.list_implementations(str(tmp_path))

    assert selected["ok"] is True
    assert listed["active"] == "agent-lsp"
    assert set(listed["implementations"]) == {"ag-lsp", "agent-lsp"}
    assert synced == [tmp_path]


def test_language_feature_state_survives_implementation_switch(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="ag-lsp", display_name="AG LSP")
    )
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="agent-lsp", display_name="Agent LSP")
    )
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    lsp_config_api._set_language_feature_enabled(tmp_path, "python", True)

    assert lsp_config_api.select_implementation(str(tmp_path), "ag-lsp")["ok"] is True
    assert lsp_config_api.select_implementation(str(tmp_path), "agent-lsp")["ok"] is True

    assert get_feature_state(tmp_path, "coding-lsp", "language", "python").enabled is True


def test_open_file_session_uses_sync_document(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    nested = tmp_path / "src" / "pkg" / "mod.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("x = 1\n", encoding="utf-8")
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    set_feature_state(
        tmp_path,
        "coding-lsp",
        "language",
        "python",
        FeatureState(enabled=True),
    )

    mock_session = MagicMock()
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda project_root, language, server: mock_session)

    lsp_api.document_symbols(str(nested))

    mock_session.sync_document.assert_called_once()
