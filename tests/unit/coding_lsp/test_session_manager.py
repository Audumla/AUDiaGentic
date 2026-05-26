from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from audiagentic.components.optional.coding_lsp.session_manager import SessionManager
from audiagentic.components.optional.coding_lsp.lsp_lifecycle import ServerConfig


def _python_config() -> ServerConfig:
    return ServerConfig(
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py", ".pyi"],
        label="python",
    )


def test_initial_status_empty() -> None:
    mgr = SessionManager()
    status = mgr.status()
    assert status["project_roots"] == 0
    assert status["total_sessions"] == 0


def test_get_or_create_initializes_session() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.optional.coding_lsp.session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mock.initialize.assert_called_once()
        mock.initialized.assert_called_once()


def test_get_or_create_reuses_existing() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.optional.coding_lsp.session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mgr.get_or_create("/tmp", "python", _python_config())
        assert MockSession.call_count == 1


def test_shutdown_session() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.optional.coding_lsp.session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mgr.shutdown_session("/tmp", "python")
        mock.shutdown.assert_called_once()


def test_shutdown_all() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.optional.coding_lsp.session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        mgr.shutdown_all()
        mock.shutdown.assert_called_once()
        assert mgr.status()["total_sessions"] == 0


def test_idle_check_shuts_down_old_sessions() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.optional.coding_lsp.session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        # Mark as old — find actual root key
        root_key = list(mgr._last_used.keys())[0]
        mgr._last_used[root_key]["python"] = time.monotonic() - 2000
        shutdown = mgr.idle_check(timeout=100)
        assert len(shutdown) == 1
        mock.shutdown.assert_called_once()


def test_idle_check_keeps_recent_sessions() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.optional.coding_lsp.session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        shutdown = mgr.idle_check(timeout=100)
        assert len(shutdown) == 0


def test_status_reports_sessions() -> None:
    mgr = SessionManager()
    with patch("audiagentic.components.optional.coding_lsp.session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        mock.server_config = _python_config()
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", _python_config())
        status = mgr.status()
        assert status["project_roots"] == 1
        assert status["total_sessions"] == 1
