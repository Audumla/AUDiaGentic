from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from audiagentic.components.coding_lsp import (
    lsp_api,
    lsp_config_api,
    lsp_session_resolution,
    lsp_status_ops,
)
from audiagentic.components.coding_lsp.coding_lsp_config import write_lsp_config
from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig
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

    rust_server = ServerConfig(command=["rust-analyzer"], file_extensions=[".rs"], label="rust", server_id="rust")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda project_root: {"rust": [rust_server]})

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
    monkeypatch.setattr(lsp_status_ops, "resolve_active_runtime_servers", lambda project_root: {})

    result = lsp_api.diagnostics(".", min_severity=2, limit=10)

    assert result == {"file:///tmp/test.py": []}
    assert called["min_severity"] == 2
    assert called["limit"] == 10


def test_diagnostics_initializes_active_sessions(monkeypatch) -> None:
    server = ServerConfig(command=["pyright-langserver", "--stdio"], file_extensions=[".py"], server_id="pyright")
    initialized: list[tuple[Path, str, ServerConfig]] = []

    monkeypatch.setattr(lsp_status_ops, "resolve_active_runtime_servers", lambda project_root: {"python": [server]})

    def _fake_get_or_create(project_root, language, server_config):
        initialized.append((project_root, language, server_config))
        return MagicMock()

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)
    monkeypatch.setattr(lsp_api._session_manager, "diagnostics", lambda project_root, **kwargs: {})

    lsp_api.diagnostics(".")

    assert initialized == [(Path.cwd(), "python", server)]


def test_diagnostics_skips_broken_sessions(monkeypatch) -> None:
    pyright = ServerConfig(command=["pyright-langserver", "--stdio"], file_extensions=[".py"], server_id="pyright")
    ruff = ServerConfig(command=["ruff", "server"], file_extensions=[".py"], server_id="ruff")
    attempted: list[str] = []

    monkeypatch.setattr(
        lsp_status_ops,
        "resolve_active_runtime_servers",
        lambda project_root: {"python": [pyright], "python-ruff": [ruff]},
    )

    def _fake_get_or_create(project_root, language, server_config):
        attempted.append(server_config.server_id)
        if server_config.server_id == "pyright":
            raise RuntimeError("boom")
        return MagicMock()

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)
    monkeypatch.setattr(
        lsp_api._session_manager,
        "diagnostics",
        lambda project_root, **kwargs: {"file:///tmp/test.py": []},
    )

    result = lsp_api.diagnostics(".")

    assert result == {"file:///tmp/test.py": []}
    assert attempted == ["pyright", "ruff"]


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
            implementation="blackwell-agent-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="blackwell-agent-lsp.mcp-args",
        )
    )
    lsp_config_api._set_language_feature_enabled(tmp_path, "python", True)
    set_implementation_state(
        tmp_path,
        "coding-lsp",
        "blackwell-agent-lsp",
        ImplementationState(enabled=True),
    )
    monkeypatch.setattr(lsp_config_api, "detect_missing", lambda probes, ids: [])

    status = lsp_config_api.config_status(str(tmp_path))

    assert status["implementation"] == "blackwell-agent-lsp"
    assert status["languages"]["python"]["feature_enabled"] is True
    assert status["languages"]["python"]["feature_options"] == {}


def test_list_and_select_implementations(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="ag-lsp", display_name="AG LSP")
    )
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="blackwell-agent-lsp", display_name="Agent LSP")
    )
    synced: list[Path] = []
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: synced.append(root))

    selected = lsp_config_api.select_implementation(str(tmp_path), "blackwell-agent-lsp")
    listed = lsp_config_api.list_implementations(str(tmp_path))

    assert selected["ok"] is True
    assert listed["active"] == "blackwell-agent-lsp"
    assert set(listed["implementations"]) == {"ag-lsp", "blackwell-agent-lsp"}
    assert synced == [tmp_path]


def test_language_feature_state_survives_implementation_switch(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="ag-lsp", display_name="AG LSP")
    )
    feature_registry.register(
        ImplementationDescriptor(parent="coding-lsp", implementation_id="blackwell-agent-lsp", display_name="Agent LSP")
    )
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    lsp_config_api._set_language_feature_enabled(tmp_path, "python", True)

    assert lsp_config_api.select_implementation(str(tmp_path), "ag-lsp")["ok"] is True
    assert lsp_config_api.select_implementation(str(tmp_path), "blackwell-agent-lsp")["ok"] is True

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


def test_resolve_language_server_auto_enables_language(tmp_path: Path, monkeypatch) -> None:
    """When a file extension matches an unconfigured language, the language should be auto-enabled."""
    (tmp_path / ".audiagentic").mkdir()
    ts_file = tmp_path / "src" / "agent.ts"
    ts_file.parent.mkdir(parents=True)
    ts_file.write_text("export const x = 1;\n", encoding="utf-8")

    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature="typescript",
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    state = get_feature_state(tmp_path, "coding-lsp", "language", "typescript")
    assert state.enabled is False

    mock_server = MagicMock()
    captured: dict[str, object] = {}

    def _fake_get_or_create(project_root, language, server):
        captured["language"] = language
        captured["server"] = server
        mock_session = MagicMock()
        return mock_session

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)

    result = lsp_api.definition(str(ts_file), "1:1")

    assert isinstance(result, list)
    assert captured.get("language") == "typescript"
    updated_state = get_feature_state(tmp_path, "coding-lsp", "language", "typescript")
    assert updated_state.enabled is True


def test_resolve_language_server_matches_makefile_basename(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    mk = tmp_path / "Makefile"
    mk.write_text("all:\n\t@echo ok\n", encoding="utf-8")

    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature="make",
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    state = get_feature_state(tmp_path, "coding-lsp", "language", "make")
    assert state.enabled is False

    captured: dict[str, object] = {}

    def _fake_get_or_create(project_root, language, server):
        captured["language"] = language
        mock_session = MagicMock()
        return mock_session

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)
    monkeypatch.setattr(
        lsp_session_resolution,
        "resolve_active_runtime_servers",
        lambda project_root: {"make": [ServerConfig(command=["make-ls"], file_extensions=["Makefile"], server_id="make")]},
    )

    result = lsp_api.document_symbols(str(mk))

    assert isinstance(result, list)
    assert captured.get("language") == "make"


def test_resolve_language_server_auto_enables_yaml(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    yaml_file = tmp_path / "docker-compose.yml"
    yaml_file.write_text("services:\n  app:\n    image: busybox\n", encoding="utf-8")

    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature="yaml",
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    state = get_feature_state(tmp_path, "coding-lsp", "language", "yaml")
    assert state.enabled is False

    captured: dict[str, object] = {}

    def _fake_get_or_create(project_root, language, server):
        captured["language"] = language
        mock_session = MagicMock()
        return mock_session

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)

    result = lsp_api.document_symbols(str(yaml_file))

    assert isinstance(result, list)
    assert captured.get("language") == "yaml"
    updated_state = get_feature_state(tmp_path, "coding-lsp", "language", "yaml")
    assert updated_state.enabled is True


# ── CAP02: Python pull diagnostics ──────────────────────────────────────────

def test_file_diagnostics_uses_pull_when_server_advertises_diagnostic_provider(tmp_path: Path, monkeypatch) -> None:
    """When server advertises diagnosticProvider, file_diagnostics uses pull path."""
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    server = ServerConfig(command=["ruff", "server"], file_extensions=[".py"], server_id="ruff")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session._supports_document_diagnostic.return_value = True
    mock_session.file_diagnostics.return_value = [{"message": "unused", "severity": 2}]
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.file_diagnostics(str(py_file))
    assert len(result) == 1
    assert result[0]["message"] == "unused"
    mock_session.file_diagnostics.assert_called_once()


def test_file_diagnostics_falls_back_to_push_when_no_pull(tmp_path: Path, monkeypatch) -> None:
    """When server lacks diagnosticProvider, file_diagnostics uses push path."""
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    server = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session._supports_document_diagnostic.return_value = False
    mock_session.file_diagnostics.return_value = [{"message": "type error", "severity": 1}]
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.file_diagnostics(str(py_file))
    assert len(result) == 1
    assert result[0]["message"] == "type error"


# ── CAP04: Read-only tools ──────────────────────────────────────────────────

def test_inlay_hints_returns_hints(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    server = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session.has_capability.return_value = True
    mock_session.inlay_hints.return_value = [{"label": "int", "position": {"line": 0, "character": 0}}]
    mock_session.sync_document = MagicMock()
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.inlay_hints(str(py_file), "1:1", "1:10")
    assert len(result) == 1
    assert result[0]["label"] == "int"


def test_signature_help_returns_signatures(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("print()\n", encoding="utf-8")

    server = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session.has_capability.return_value = True
    mock_session.signature_help.return_value = {
        "signatures": [{"label": "print(*args)", "parameters": [{"label": "*args"}]}],
        "activeSignature": 0,
    }
    mock_session.sync_document = MagicMock()
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.signature_help(str(py_file), "1:7")
    assert result is not None
    assert len(result["signatures"]) == 1
    assert result["signatures"][0]["label"] == "print(*args)"


def test_type_hierarchy_returns_supertypes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("class Foo: pass\n", encoding="utf-8")

    server = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session.has_capability.return_value = True
    mock_session.type_hierarchy_supertypes.return_value = [
        {"name": "object", "kind": 5, "location": {"uri": lsp_api.file_to_uri(py_file), "range": {}}}
    ]
    mock_session.sync_document = MagicMock()
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.type_hierarchy(str(py_file), "1:8")
    assert len(result) == 1
    assert result[0]["name"] == "object"


def test_completion_returns_items(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("import os\nos.\n", encoding="utf-8")

    server = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session.has_capability.return_value = True
    mock_session.completion.return_value = [
        {"label": "path", "kind": 5, "detail": "module", "documentation": "os.path module"},
    ]
    mock_session.sync_document = MagicMock()
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.completion(str(py_file), "2:4", trigger_character=".")
    assert len(result) == 1
    assert result[0]["label"] == "path"


# ── CAP05: Mutation gating ──────────────────────────────────────────────────

def test_rename_preview_blocked_when_mutation_disabled(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    set_implementation_state(
        tmp_path, "coding-lsp", "ag-lsp",
        ImplementationState(enabled=True, options={"mutation-enabled": False}),
    )

    result = lsp_api.rename_preview(str(py_file), "1:1", "new_name")
    assert result is not None
    assert "error" in result
    assert "EXT-LSP-010" in result.get("code", "")


def test_rename_preview_allowed_when_mutation_enabled(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    set_implementation_state(
        tmp_path, "coding-lsp", "ag-lsp",
        ImplementationState(enabled=True, options={"mutation-enabled": True}),
    )

    server = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session.has_capability.return_value = True
    mock_session.rename.return_value = {"changes": {}}
    mock_session.sync_document = MagicMock()
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.rename_preview(str(py_file), "1:1", "new_name")
    assert result is not None
    assert "error" not in result


def test_apply_workspace_edit_blocked_when_mutation_disabled(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    set_implementation_state(
        tmp_path, "coding-lsp", "ag-lsp",
        ImplementationState(enabled=True, options={"mutation-enabled": False}),
    )

    result = lsp_api.apply_workspace_edit(str(py_file), {"changes": {}})
    assert "error" in result
    assert "EXT-LSP-010" in result.get("code", "")


# ── CAP06: Capability matrix ────────────────────────────────────────────────

def test_server_capabilities_includes_type_hierarchy_when_supported(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    server = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [server]})

    mock_session = MagicMock()
    mock_session.has_capability.side_effect = lambda m: m in (
        "textDocument/definition", "textDocument/hover",
        "textDocument/typeHierarchy", "workspace/symbol",
    )
    mock_session.capabilities.return_value = {"typeHierarchyProvider": True}
    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", lambda pr, lang, cfg: mock_session)

    result = lsp_api.server_capabilities(str(py_file))
    assert "typeHierarchy" in result["supported"]


def test_server_capabilities_skips_failed_server_and_reports_it(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    broken = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright", label="Python (pyright)")
    good = ServerConfig(command=["ruff", "server"], file_extensions=[".py"], server_id="ruff", label="Python (ruff)")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [broken], "python-ruff": [good]})

    good_session = MagicMock()
    good_session.has_capability.side_effect = lambda m: m == "textDocument/hover"
    good_session.capabilities.return_value = {"hoverProvider": True}

    def _fake_get_or_create(project_root, language, cfg):
        if cfg.server_id == "pyright":
            raise RuntimeError("init failed")
        return good_session

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)

    result = lsp_api.server_capabilities(str(py_file))

    assert "hover" in result["supported"]
    assert any(server.get("error") == "failed to initialize" for server in result["servers"])


def test_open_file_session_skips_failed_server(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".audiagentic").mkdir()
    py_file = tmp_path / "test.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    broken = ServerConfig(command=["pyright-langserver"], file_extensions=[".py"], server_id="pyright")
    good = ServerConfig(command=["ruff", "server"], file_extensions=[".py"], server_id="ruff")
    monkeypatch.setattr(lsp_session_resolution, "discover_servers_multi", lambda pr: {"python": [broken], "python-ruff": [good]})

    good_session = MagicMock()
    good_session.has_capability.return_value = True
    good_session.sync_document = MagicMock()

    def _fake_get_or_create(project_root, language, cfg):
        if cfg.server_id == "pyright":
            raise RuntimeError("init failed")
        return good_session

    monkeypatch.setattr(lsp_api._session_manager, "get_or_create", _fake_get_or_create)

    session, _ = lsp_api._open_file_session(str(py_file), "textDocument/hover")

    assert session is good_session
    good_session.sync_document.assert_called_once()


# ── CAP07: Install recipe validation ────────────────────────────────────────

def test_ruff_language_spec_has_dependency_recipe() -> None:
    """Verify ruff language spec includes install recipe via dependency."""
    from audiagentic.components.coding_lsp import language_registry
    spec = language_registry.get_language("python-ruff")
    assert spec is not None
    assert spec.dependency is not None
    assert spec.dependency.id == "ruff"
    assert spec.dependency.cfg.get("package") == "ruff"
    assert spec.dependency.cfg.get("probe") == "binary:ruff"
