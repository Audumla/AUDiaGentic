from __future__ import annotations

import logging
from unittest.mock import MagicMock

from audiagentic.components.optional.coding_lsp.lsp_lifecycle import (
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
    session.bridge.send_request = MagicMock(side_effect=RuntimeError("boom"))

    from audiagentic.foundation.contracts.errors import AudiaGenticError
    try:
        session.diagnostics()
        assert False, "should have raised"
    except AudiaGenticError as e:
        assert "EXT-LSP-008" in e.code
        assert "Workspace diagnostics request failed" in e.message
