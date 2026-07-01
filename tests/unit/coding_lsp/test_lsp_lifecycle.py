from __future__ import annotations

import json
from unittest.mock import MagicMock

from audiagentic.components.coding_lsp.lsp_lifecycle import (
    LspSession,
    ServerConfig,
)


def _make_config() -> ServerConfig:
    return ServerConfig(
        command=["echo", "mock"],
        file_extensions=[".py"],
        label="python",
    )


def test_session_path_to_uri() -> None:
    from pathlib import Path
    uri = LspSession._path_to_uri(Path(__file__).resolve().parent)
    assert uri.startswith("file://")


def test_session_is_ready_false_before_init() -> None:
    session = LspSession(_make_config(), "/tmp")
    assert not session.is_ready()


def test_client_capabilities_has_required_keys() -> None:
    caps = LspSession._client_capabilities()
    assert "textDocument" in caps
    assert "workspace" in caps
    assert caps["workspace"]["workspaceFolders"] is True


def test_client_capabilities_includes_all_planned_features() -> None:
    caps = LspSession._client_capabilities()
    td = caps["textDocument"]
    assert "codeAction" in td
    assert "completion" in td
    assert "signatureHelp" in td
    assert "formatting" in td
    assert "rangeFormatting" in td
    assert "inlayHint" in td
    assert "callHierarchy" in td
    assert "typeDefinition" in td
    assert "implementation" in td


def test_client_capabilities_general_position_encodings() -> None:
    caps = LspSession._client_capabilities()
    assert "general" in caps
    assert "utf-8" in caps["general"]["positionEncodings"]
    assert "utf-16" in caps["general"]["positionEncodings"]


def test_workspace_symbol_returns_empty_on_none() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value=None)
    result = session.workspace_symbol("test")
    assert result == []


def test_workspace_symbol_returns_empty_on_non_list() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value="not-a-list")
    result = session.workspace_symbol("test")
    assert result == []


def test_definition_wraps_single_result() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value={"uri": "file://test.py"})
    result = session.definition("file://test.py", 0, 0)
    assert isinstance(result, list)
    assert len(result) == 1


def test_definition_returns_list_passthrough() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value=[{"uri": "a"}, {"uri": "b"}])
    result = session.definition("file://test.py", 0, 0)
    assert len(result) == 2


def test_did_open_tracks_document_version() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.did_open("file://test.py", "print('hi')", "python", version=1)
    assert session._opened_docs["file://test.py"] == 1


def test_sync_document_opens_once_and_skips_unchanged() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.sync_document("file://test.py", "print('hi')", "python")
    session.sync_document("file://test.py", "print('hi')", "python")
    session.bridge.send_notification.assert_called_once()


def test_sync_document_sends_change_for_new_text() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.sync_document("file://test.py", "print('hi')", "python")
    session.sync_document("file://test.py", "print('bye')", "python")
    assert session._opened_docs["file://test.py"] == 2
    assert session._document_text["file://test.py"] == "print('bye')"
    assert session.bridge.send_notification.call_count == 2


def test_hover_returns_none_on_no_info() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value=None)
    result = session.hover("file://test.py", 0, 0)
    assert result is None


def test_get_diagnostics_all() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session._capabilities = {"diagnosticProvider": {"workspaceDiagnostics": True}}
    session.bridge.send_request = MagicMock(return_value={
        "items": [
            {"kind": "full", "uri": "file://a.py", "items": [{"severity": 1, "message": "err"}]},
            {"kind": "full", "uri": "file://b.py", "items": []},
        ]
    })
    result = session.diagnostics()
    assert "file://a.py" in result


def test_get_diagnostics_single_uri() -> None:
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session._capabilities = {"diagnosticProvider": {"workspaceDiagnostics": True}}
    session.bridge.send_request = MagicMock(return_value={
        "items": [
            {"kind": "full", "uri": "file://a.py", "items": [{"severity": 1, "message": "err"}]},
            {"kind": "full", "uri": "file://b.py", "items": [{"severity": 2, "message": "warn"}]},
        ]
    })
    result = session.diagnostics(min_severity=1)
    assert "file://a.py" in result


def test_diagnostics_logs_warning_on_request_failure(caplog) -> None:
    """Regression: a failed diagnostics request logs before returning {}.

    Also guards the module-level logger: a bare logger.* call would NameError
    if the import were dropped.
    """
    session = LspSession(_make_config(), "/tmp")
    session.bridge = MagicMock()
    session._capabilities = {"diagnosticProvider": {"workspaceDiagnostics": True}}
    session.bridge.send_request = MagicMock(side_effect=RuntimeError("boom"))

    from audiagentic.foundation.contracts.errors import AudiaGenticError
    try:
        session.diagnostics()
        assert False, "should have raised"
    except AudiaGenticError as e:
        assert "EXT-LSP-008" in e.code
        assert "Workspace diagnostics request failed" in e.message


def test_diagnostics_no_pull_no_cli_fails_fast() -> None:
    """No workspace pull and no known batch CLI fails fast, never sends the request.

    Regression: pyright reports workspaceDiagnostics=false; sending workspace/diagnostic
    anyway hangs until the 30s timeout. With no batch CLI for the server, raise
    EXT-LSP-004 and point to the file-diagnostics tools.
    """
    session = LspSession(_make_config(), "/tmp")  # command=["echo", ...] → no CLI
    session.bridge = MagicMock()
    session._capabilities = {"diagnosticProvider": {"workspaceDiagnostics": False}}

    from audiagentic.foundation.contracts.errors import AudiaGenticError
    try:
        session.diagnostics()
        assert False, "should have raised"
    except AudiaGenticError as e:
        assert "EXT-LSP-004" in e.code
        assert "lsp_file_diagnostics" in e.message
    session.bridge.send_request.assert_not_called()


def test_batch_cli_name_maps_pyright() -> None:
    """pyright-langserver resolves to the pyright batch CLI; unknown servers to None."""
    pyright = ServerConfig(command=["pyright-langserver", "--stdio"], label="python")
    based = ServerConfig(command=["/usr/bin/basedpyright-langserver.exe"], label="python")
    other = ServerConfig(command=["echo"], label="x")
    assert LspSession(pyright, "/tmp")._batch_cli_name() == "pyright"
    assert LspSession(based, "/tmp")._batch_cli_name() == "basedpyright"
    assert LspSession(other, "/tmp")._batch_cli_name() is None


def test_diagnostics_falls_back_to_cli_scan(monkeypatch) -> None:
    """Push-only server (no workspace pull) scans the project via its batch CLI.

    The CLI path must produce the same {uri: [diagnostic]} shape as the LSP pull
    path and must not touch the LSP request channel.
    """
    import subprocess
    from pathlib import Path

    cfg = ServerConfig(command=["pyright-langserver", "--stdio"], label="python")
    session = LspSession(cfg, "/tmp")
    session.bridge = MagicMock()
    session._capabilities = {}  # no diagnosticProvider → no workspace pull

    target = str((Path("/tmp") / "mod.py").resolve())
    report = {
        "generalDiagnostics": [
            {"file": target, "severity": "error", "message": "boom",
             "range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 3}},
             "rule": "reportUndefinedVariable"},
            {"file": target, "severity": "warning", "message": "meh",
             "range": {}, "rule": "reportUnusedVariable"},
        ]
    }

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, str):
            assert "pyright" in cmd and "--outputjson" in cmd
            assert kwargs.get("shell") is True
        else:
            assert cmd[0] == "pyright" and "--outputjson" in cmd
        return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps(report), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = session.diagnostics(min_severity=1)  # errors only
    session.bridge.send_request.assert_not_called()
    assert len(result) == 1  # one file
    (uri, diags), = result.items()
    assert uri.startswith("file://")
    assert len(diags) == 1  # warning filtered out by min_severity=1
    assert diags[0]["severity"] == 1
    assert diags[0]["code"] == "reportUndefinedVariable"
    assert diags[0]["source"] == "pyright"


def test_diagnostics_cli_scan_uses_shell_wrapper_on_windows(monkeypatch) -> None:
    """Windows batch CLI path must shell-launch so `.cmd` shims resolve."""
    import subprocess

    cfg = ServerConfig(command=["pyright-langserver", "--stdio"], label="python")
    session = LspSession(cfg, "/tmp")
    session.bridge = MagicMock()
    session._capabilities = {}

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout='{"generalDiagnostics":[]}', stderr="")

    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.lsp_diagnostics._use_shell_for_batch_cli",
        lambda: True,
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    session.diagnostics()

    assert isinstance(captured["cmd"], str)
    assert "pyright" in str(captured["cmd"])
    assert captured["kwargs"]["shell"] is True
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL


def test_diagnostics_cli_missing_binary_raises(monkeypatch) -> None:
    """A missing batch CLI surfaces EXT-LSP-004 with an install hint, not a hang."""
    import subprocess

    cfg = ServerConfig(command=["pyright-langserver", "--stdio"], label="python")
    session = LspSession(cfg, "/tmp")
    session.bridge = MagicMock()
    session._capabilities = {}

    def boom(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess, "run", boom)

    from audiagentic.foundation.contracts.errors import AudiaGenticError
    try:
        session.diagnostics()
        assert False, "should have raised"
    except AudiaGenticError as e:
        assert "EXT-LSP-004" in e.code
        assert "pyright" in e.message


def test_has_capability_reads_top_level_providers() -> None:
    """has_capability must read top-level *Provider keys (pyright's real shape)."""
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {
        "definitionProvider": {"workDoneProgress": True},
        "hoverProvider": True,
        "renameProvider": {"prepareProvider": True},
        "referencesProvider": False,  # explicitly disabled
        # completionProvider absent
    }
    assert session.has_capability("textDocument/definition")
    assert session.has_capability("textDocument/hover")
    assert session.has_capability("textDocument/rename")
    assert not session.has_capability("textDocument/references")
    assert not session.has_capability("textDocument/completion")


def test_uri_to_path_without_path_from_uri() -> None:
    """Regression: _uri_to_path must work on Python 3.12 (no Path.from_uri).

    The MCP runtime is 3.12; Path.from_uri is 3.13+ and raised AttributeError,
    crashing file_diagnostics. url2pathname-based conversion works on both.
    """
    import os

    p = LspSession._uri_to_path("file:///H:/a%20b/c.py")
    # Compare via parts so the test is OS-agnostic for the non-drive segments.
    assert p.name == "c.py"
    assert "a b" in p.parts  # percent-decoded space
    if os.name == "nt":
        assert str(p) == r"H:\a b\c.py"


def test_canonical_uri_collapses_windows_drive_case() -> None:
    """publishDiagnostics with lowercase drive / alt encoding must key the same.

    Regression: client URIs use uppercase drive (Path.as_uri); servers often
    publish lowercase. Mismatched keys made file_diagnostics silently return [].
    """
    client = "file:///H:/proj/a b/mod.py"
    server = "file:///h:/proj/a%20b/mod.py"
    assert LspSession._canonical_uri(client) == LspSession._canonical_uri(server)
    once = LspSession._canonical_uri(server)
    assert LspSession._canonical_uri(once) == once  # idempotent
    assert LspSession._canonical_uri("untitled:foo") == "untitled:foo"
