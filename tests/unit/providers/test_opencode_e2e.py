"""End-to-end test: ag-lsp MCP must appear in .opencode/opencode.json after sync.

This test does NOT mock any part of the projection path. It:
1. Sets up a real project root with feature state enabling opencode
2. Calls the actual sync function through the family API
3. Reads the actual .opencode/opencode.json file
4. Asserts ag-lsp is present with correct command/args
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.contracts.lsp_mcp_projection import (
    LspMcpProjectionEntry,
    LspMcpProjectionRequest,
)
from audiagentic.components.providers.providers_api import manage_lsp_mcp_projection_all
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


def _enable_opencode(project_root: Path) -> None:
    """Enable opencode provider in feature state so it appears in enabled_provider_ids()."""
    set_implementation_state(
        project_root,
        "providers",
        "opencode",
        ImplementationState(enabled=True),
    )


def _make_request() -> LspMcpProjectionRequest:
    entry = LspMcpProjectionEntry(
        managed_id="coding-lsp/ag-lsp",
        name="ag-lsp",
        command="python",
        args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
    )
    return LspMcpProjectionRequest(
        managed_ids=("coding-lsp/ag-lsp",),
        entries=(entry,),
    )


def test_ag_lsp_appears_in_opencode_json_e2e(tmp_path: Path) -> None:
    """Full end-to-end: enabling opencode + syncing generic-lsp-mcp writes ag-lsp to .opencode/opencode.json."""
    _enable_opencode(tmp_path)

    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="apply",
        request=_make_request(),
    )

    synced = [r.provider_id for r in results if r.ok]
    assert "opencode" in synced

    opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
    assert opencode_cfg_path.exists(), f"Expected .opencode/opencode.json to exist at {opencode_cfg_path}"

    data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
    servers = data.get("mcp", {})

    assert "ag-lsp" in servers, f"ag-lsp not found in .opencode/opencode.json. Keys: {list(servers.keys())}"
    assert servers["ag-lsp"]["type"] == "local"
    assert servers["ag-lsp"]["command"][0] == "python"
    assert servers["ag-lsp"]["command"][1:] == ["-m", "audiagentic.components.coding_lsp.lsp_mcp"]


def test_ag_lsp_not_written_when_opencode_disabled(tmp_path: Path) -> None:
    """When opencode is NOT enabled, ag-lsp should NOT be written."""
    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="apply",
        request=_make_request(),
    )

    for r in results:
        if r.provider_id == "opencode":
            assert not r.synced or not any(mid in r.synced for mid in ("coding-lsp/ag-lsp",))

    opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
    assert not opencode_cfg_path.exists(), "opencode.json should not exist when opencode is disabled"


def test_claude_and_opencode_both_receive_ag_lsp(tmp_path: Path, monkeypatch) -> None:
    """Both claude and opencode should receive ag-lsp when both are enabled."""
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.state import set_implementation_state

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    set_implementation_state(
        tmp_path, "providers", "opencode", ImplementationState(enabled=True)
    )
    set_implementation_state(
        tmp_path, "providers", "claude", ImplementationState(enabled=True)
    )

    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="apply",
        request=_make_request(),
    )

    synced_ids = [r.provider_id for r in results if r.ok]
    assert "opencode" in synced_ids
    assert "claude" in synced_ids

    opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
    assert opencode_cfg_path.exists()
    data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
    assert "ag-lsp" in data.get("mcp", {})

    claude_cfg_path = home / ".claude" / "mcp.json"
    assert claude_cfg_path.exists()
    data = json.loads(claude_cfg_path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    assert "ag-lsp" in servers
