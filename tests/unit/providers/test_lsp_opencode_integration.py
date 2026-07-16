"""End-to-end test: ag-lsp MCP must appear in .opencode/opencode.json after sync.

Tests the direct projection path (not event bus) to avoid test fragility.
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.adapters.mcp_opencode import (
    write_opencode_mcp,
)
from audiagentic.components.providers.contracts.lsp_mcp_projection import (
    LspMcpProjectionEntry,
    LspMcpProjectionRequest,
)
from audiagentic.components.providers.providers_api import manage_lsp_mcp_projection_all
from audiagentic.components.providers.services.provider_config import set_provider_enabled
from audiagentic.foundation.mcp import McpServerEntry


def _make_apply_request() -> LspMcpProjectionRequest:
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


def _make_prune_request() -> LspMcpProjectionRequest:
    return LspMcpProjectionRequest(
        managed_ids=("coding-lsp/ag-lsp",),
    )


def test_ag_lsp_appears_in_opencode_json(tmp_path: Path) -> None:
    """When opencode is enabled, sync writes ag-lsp to .opencode/opencode.json."""
    set_provider_enabled(tmp_path, "opencode", enabled=True)

    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="apply",
        request=_make_apply_request(),
    )

    synced_ids = [r.provider_id for r in results if r.ok]
    assert "opencode" in synced_ids

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

    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="apply",
        request=_make_apply_request(),
    )

    for r in results:
        if r.provider_id == "opencode":
            assert r.ok is True

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

    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="prune",
        request=_make_prune_request(),
    )

    for r in results:
        if r.provider_id == "opencode":
            assert r.ok is True

    data = json.loads(opencode_json.read_text(encoding="utf-8"))
    mcp_servers = data.get("mcp", {})
    assert "ag-lsp" not in mcp_servers, f"ag-lsp should have been pruned. Keys: {list(mcp_servers.keys())}"
