"""End-to-end test: ag-lsp MCP must appear in .opencode/opencode.json after sync.

Tests the direct projection path (not event bus) to avoid test fragility.
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.adapters.mcp_opencode import (
    write_opencode_mcp,
)
from audiagentic.components.providers.services.lsp_projection import (
    prune_generic_lsp_mcp_from_provider_configs,
    sync_generic_lsp_mcp_to_provider_configs,
)
from audiagentic.components.providers.services.provider_config import set_provider_enabled
from audiagentic.foundation.mcp import McpServerEntry


def test_ag_lsp_appears_in_opencode_json(tmp_path: Path) -> None:
    """When opencode is enabled, sync writes ag-lsp to .opencode/opencode.json."""
    set_provider_enabled(tmp_path, "opencode", enabled=True)

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

    opencode_json = tmp_path / ".opencode" / "opencode.json"
    assert opencode_json.exists()
    data = json.loads(opencode_json.read_text(encoding="utf-8"))
    mcp_servers = data.get("mcp", {})
    assert "ag-lsp" in mcp_servers, f"ag-lsp not found. Keys: {list(mcp_servers.keys())}"
    server = mcp_servers["ag-lsp"]
    assert server["type"] == "local"
    assert server["command"][0] == "python"


def test_ag_lsp_mgmt_does_not_appear_in_opencode_json(tmp_path: Path) -> None:
    """ag-lsp-mgmt must NOT appear in opencode config."""
    set_provider_enabled(tmp_path, "opencode", enabled=True)

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

    opencode_json = tmp_path / ".opencode" / "opencode.json"
    data = json.loads(opencode_json.read_text(encoding="utf-8"))
    mcp_servers = data.get("mcp", {})
    assert "ag-lsp-mgmt" not in mcp_servers


def test_pruning_removes_ag_lsp_from_opencode_json(tmp_path: Path) -> None:
    """When pruning, ag-lsp should be removed from opencode config."""
    set_provider_enabled(tmp_path, "opencode", enabled=True)

    opencode_json = tmp_path / ".opencode" / "opencode.json"
    write_opencode_mcp(opencode_json, {
        "ag-lsp": McpServerEntry(
            name="ag-lsp",
            command="python",
            args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
        ),
    })

    # Set up managed MCP registry so prune knows ownership
    registry_dir = tmp_path / ".audiagentic" / "runtime" / "providers"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = registry_dir / "managed-mcp-servers.json"
    registry_file.write_text(
        json.dumps({
            "contract-version": "v1",
            "providers": {
                "opencode": {
                    "coding-lsp/ag-lsp": "ag-lsp",
                }
            }
        }, indent=2)
    )

    result = prune_generic_lsp_mcp_from_provider_configs(tmp_path, {"coding-lsp/ag-lsp"})

    assert result["ok"] is True

    data = json.loads(opencode_json.read_text(encoding="utf-8"))
    mcp_servers = data.get("mcp", {})
    assert "ag-lsp" not in mcp_servers, f"ag-lsp should have been pruned. Keys: {list(mcp_servers.keys())}"
