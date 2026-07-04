"""End-to-end test: ag-lsp MCP must appear in .opencode/opencode.json after sync.

This test does NOT mock any part of the projection path. It:
1. Sets up a real project root with feature state enabling opencode
2. Calls the actual sync function
3. Reads the actual .opencode/opencode.json file
4. Asserts ag-lsp is present with correct command/args
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.services.lsp_projection import (
    sync_generic_lsp_mcp_to_provider_configs,
)
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.mcp import McpServerEntry


def _enable_opencode(project_root: Path) -> None:
    """Enable opencode provider in feature state so it appears in enabled_provider_ids()."""
    set_implementation_state(
        project_root,
        "providers",
        "opencode",
        ImplementationState(enabled=True),
    )


def test_ag_lsp_appears_in_opencode_json_e2e(tmp_path: Path) -> None:
    """Full end-to-end: enabling opencode + syncing generic-lsp-mcp writes ag-lsp to .opencode/opencode.json."""
    # 1. Enable opencode in feature state
    _enable_opencode(tmp_path)

    # 2. Call the actual sync function (no mocks)
    ag_lsp_entry = {
        "coding-lsp/ag-lsp": (
            "ag-lsp",
            McpServerEntry(
                name="ag-lsp",
                command="python",
                args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
                env={},
            ),
        ),
    }

    result = sync_generic_lsp_mcp_to_provider_configs(
        tmp_path,
        ag_lsp_entry,
        {"coding-lsp/ag-lsp"},
    )

    # 3. Verify sync reported success
    assert result["ok"] is True
    assert "opencode" in result["synced"]

    # 4. Read the actual file
    opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
    assert opencode_cfg_path.exists(), f"Expected .opencode/opencode.json to exist at {opencode_cfg_path}"

    data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
    servers = data.get("mcp", {})

    # 5. Assert ag-lsp is present
    assert "ag-lsp" in servers, f"ag-lsp not found in .opencode/opencode.json. Keys: {list(servers.keys())}"
    assert servers["ag-lsp"]["type"] == "local"
    assert servers["ag-lsp"]["command"][0] == "python"
    assert servers["ag-lsp"]["command"][1:] == ["-m", "audiagentic.components.coding_lsp.lsp_mcp"]


def test_ag_lsp_not_written_when_opencode_disabled(tmp_path: Path) -> None:
    """When opencode is NOT enabled, ag-lsp should NOT be written."""
    # Don't enable opencode — leave feature state empty

    ag_lsp_entry = {
        "coding-lsp/ag-lsp": (
            "ag-lsp",
            McpServerEntry(
                name="ag-lsp",
                command="python",
                args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
                env={},
            ),
        ),
    }

    result = sync_generic_lsp_mcp_to_provider_configs(
        tmp_path,
        ag_lsp_entry,
        {"coding-lsp/ag-lsp"},
    )

    # opencode should be skipped (disabled)
    assert result["ok"] is True

    opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
    # File should not exist since no enabled provider wrote to it
    assert not opencode_cfg_path.exists(), "opencode.json should not exist when opencode is disabled"


def test_claude_and_opencode_both_receive_ag_lsp(tmp_path: Path, monkeypatch) -> None:
    """Both claude and opencode should receive ag-lsp when both are enabled."""
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.state import set_implementation_state

    # Redirect ~ expansion so claude's ~/.claude/mcp.json lands in tmp_path.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    # Enable both providers
    set_implementation_state(
        tmp_path, "providers", "opencode", ImplementationState(enabled=True)
    )
    set_implementation_state(
        tmp_path, "providers", "claude", ImplementationState(enabled=True)
    )

    ag_lsp_entry = {
        "coding-lsp/ag-lsp": (
            "ag-lsp",
            McpServerEntry(
                name="ag-lsp",
                command="python",
                args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
                env={},
            ),
        ),
    }

    result = sync_generic_lsp_mcp_to_provider_configs(
        tmp_path,
        ag_lsp_entry,
        {"coding-lsp/ag-lsp"},
    )

    assert result["ok"] is True
    assert "opencode" in result["synced"]
    assert "claude" in result["synced"]

    # Verify opencode
    opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
    assert opencode_cfg_path.exists()
    data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
    assert "ag-lsp" in data.get("mcp", {})

    # Verify claude (uses mcpServers key, writes to ~/.claude/mcp.json)
    claude_cfg_path = home / ".claude" / "mcp.json"
    assert claude_cfg_path.exists()
    data = json.loads(claude_cfg_path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    assert "ag-lsp" in servers
