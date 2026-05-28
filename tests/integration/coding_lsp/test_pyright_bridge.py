"""Integration tests for LSP bridge with real pyright."""
from __future__ import annotations

import pytest
from tests.integration.coding_lsp.conftest import requires_pyright

from audiagentic.components.optional.coding_lsp.lsp_bridge import LspJsonRpc


@requires_pyright
@pytest.mark.slow
@pytest.mark.requires_uv
@pytest.mark.timeout(60)
def test_pyright_initialize():
    """Test that pyright-langserver initializes successfully."""
    bridge = LspJsonRpc()
    try:
        bridge.launch_server(["pyright-langserver", "--stdio"])
        assert bridge.is_alive()
        result = bridge.send_request(
            "initialize",
            {
                "processId": None,
                "rootUri": None,
                "capabilities": {},
            },
            timeout=30,
        )
        assert result is not None
        assert "capabilities" in result
    finally:
        bridge.shutdown()


@requires_pyright
@pytest.mark.slow
@pytest.mark.requires_uv
@pytest.mark.timeout(90)
def test_pyright_workspace_symbols():
    """Test workspace/symbol request against pyright."""
    from pathlib import Path

    from audiagentic.components.optional.coding_lsp.lsp_lifecycle import (
        LspSession,
        ServerConfig,
    )

    project_root = Path(__file__).resolve().parents[2]
    config = ServerConfig(
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py"],
        label="python",
    )
    session = LspSession(config, project_root)
    try:
        session.initialize(timeout=30)
        session.initialized()
        # Give pyright time to index
        import time
        time.sleep(2)
        symbols = session.workspace_symbol("LspSession")
        # May or may not find anything depending on indexing state
        assert isinstance(symbols, list)
    finally:
        session.shutdown()
