from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig
from audiagentic.components.coding_lsp.lsp_session_manager import SessionManager


def _python_config() -> ServerConfig:
    return ServerConfig(
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py", ".pyi"],
        label="python",
        server_id="pyright",
    )


def test_initial_status_empty() -> None:
    mgr = SessionManager()
    status = mgr.status()
    assert status["project_roots"] == 0
    assert status["total_sessions"] == 0


def test_get_or_create_initializes_session() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mock.initialize.assert_called_once()
        mock.initialized.assert_called_once()


def test_get_or_create_reuses_existing() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mgr.get_or_create("/tmp", "python", _python_config())
        assert MockSession.call_count == 1


def test_shutdown_session() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mgr.shutdown_session("/tmp", "python")
        mock.shutdown.assert_called_once()


def test_shutdown_all() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mgr.shutdown_all()
        mock.shutdown.assert_called_once()
        assert mgr.status()["total_sessions"] == 0


def test_idle_check_shuts_down_old_sessions() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        root_key = list(mgr._last_used.keys())[0]
        mgr._last_used[root_key]["python:pyright"] = time.monotonic() - 2000
        shutdown = mgr.idle_check(timeout=100)
        assert len(shutdown) == 1
        mock.shutdown.assert_called_once()


def test_idle_check_keeps_recent_sessions() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        shutdown = mgr.idle_check(timeout=100)
        assert len(shutdown) == 0


def test_status_reports_sessions() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        mock.server_config = _python_config()
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        status = mgr.status()
        assert status["project_roots"] == 1
        assert status["total_sessions"] == 1


def test_get_diagnostics_for_project() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        mock.diagnostics.return_value = {"file:///tmp/test.py": [{"message": "bad"}]}
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        assert mgr.diagnostics("/tmp") == {"file:///tmp/test.py": [{"message": "bad"}]}


def test_two_servers_same_language_create_two_sessions() -> None:
    mgr = SessionManager()
    cfg1 = ServerConfig(command=["server-a"], file_extensions=[".py"], server_id="a")
    cfg2 = ServerConfig(command=["server-b"], file_extensions=[".py"], server_id="b")
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", cfg1)
        mgr.get_or_create("/tmp", "python", cfg2)
        assert MockSession.call_count == 2
        assert mgr.status()["total_sessions"] == 2


def test_shutdown_session_by_server_id() -> None:
    mgr = SessionManager()
    cfg1 = ServerConfig(command=["server-a"], file_extensions=[".py"], server_id="a")
    cfg2 = ServerConfig(command=["server-b"], file_extensions=[".py"], server_id="b")
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", cfg1)
        mgr.get_or_create("/tmp", "python", cfg2)
        mgr.shutdown_session("/tmp", "python", server_id="a")
        assert mgr.status()["total_sessions"] == 1


def test_diagnostics_merge_deduplicates() -> None:
    from pathlib import Path
    mgr = SessionManager()
    diag = {"source": "pyright", "code": "E001", "range": {}, "message": "err", "severity": 1}
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock1 = MagicMock()
        mock1.is_ready.return_value = True
        mock1.diagnostics.return_value = {"file:///f.py": [diag]}
        MockSession.return_value = mock1
        mgr.get_or_create("/tmp", "python", ServerConfig(command=["a"], server_id="a"))
        mock2 = MagicMock()
        mock2.is_ready.return_value = True
        mock2.diagnostics.return_value = {"file:///f.py": [diag]}
        mgr._sessions[str(Path("/tmp").resolve())]["python:b"] = mock2
        result = mgr.diagnostics("/tmp")
        assert len(result.get("file:///f.py", [])) == 1
