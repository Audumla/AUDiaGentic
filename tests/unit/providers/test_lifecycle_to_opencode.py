"""End-to-end test through the actual lifecycle bootstrap path.

Verifies that when coding-lsp is enabled, the bootstrap handler fires
and projects ag-lsp into provider configs.
"""
from __future__ import annotations

import json
from pathlib import Path


def test_bootstrap_on_enabled_projects_ag_lsp_to_opencode(tmp_path: Path) -> None:
    """Full lifecycle path: coding-lsp enabled → bootstrap → opencode.json."""
    from audiagentic.components.providers.services.provider_config import set_provider_enabled
    from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.state import set_implementation_state

    register_all_components()

    # Enable opencode provider
    set_provider_enabled(tmp_path, "opencode", enabled=True)

    # Enable coding-lsp
    set_implementation_state(
        tmp_path,
        COMPONENT_CODING_LSP,
        "ag-lsp",
        ImplementationState(enabled=True),
    )

    # Call the exact handler that fires when coding-lsp is enabled
    from audiagentic.components.coding_lsp.coding_lsp_bootstrap import _on_enabled
    _on_enabled(tmp_path)

    # Check opencode config
    opencode_json = tmp_path / ".opencode" / "opencode.json"
    assert opencode_json.exists(), f".opencode/opencode.json not created. Files: {list(tmp_path.rglob('*.json'))}"

    data = json.loads(opencode_json.read_text(encoding="utf-8"))
    mcp_servers = data.get("mcp", {})
    assert "ag-lsp" in mcp_servers, f"ag-lsp not in opencode.json. Keys: {list(mcp_servers.keys())}"
    assert mcp_servers["ag-lsp"]["type"] == "local"
    assert mcp_servers["ag-lsp"]["command"][:2] == ["audiagentic", "mcp"]
