"""Real integration test: opencode MCP projection from coding-lsp.

Tests against the actual opencode descriptor and file format to verify
that enabling coding-lsp projects ag-lsp into .opencode/opencode.json
but NOT ag-lsp-mgmt.
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.adapters.mcp_opencode import (
    read_opencode_mcp,
    write_opencode_mcp,
)
from audiagentic.components.providers.services.mcp import sync_managed_provider_mcp_subset
from audiagentic.foundation.mcp import McpServerEntry


class TestOpencodeMcpProjection:
    """Verify ag-lsp is projected into opencode's .opencode/opencode.json."""

    def test_ag_lsp_projected_into_opencode_json(self, tmp_path: Path) -> None:
        """ag-lsp MCP server should appear in .opencode/opencode.json."""
        ag_lsp_entry = McpServerEntry(
            name="ag-lsp",
            command="python",
            args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
            env={},
        )
        desired_entries = {
            "coding-lsp/ag-lsp": ("ag-lsp", ag_lsp_entry),
        }
        managed_ids = {"coding-lsp/ag-lsp"}

        result = sync_managed_provider_mcp_subset(
            provider_id="opencode",
            project_root=tmp_path,
            desired_entries=desired_entries,
            managed_ids=managed_ids,
        )

        assert result["ok"] is True

        opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
        data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
        servers = data.get("mcp", {})

        assert "ag-lsp" in servers
        assert servers["ag-lsp"]["type"] == "local"
        assert servers["ag-lsp"]["command"][0] == "python"
        assert servers["ag-lsp"]["command"][1:] == ["-m", "audiagentic.components.coding_lsp.lsp_mcp"]

    def test_ag_lsp_mgmt_not_projected_into_opencode(self, tmp_path: Path) -> None:
        """ag-lsp-mgmt should NOT appear in .opencode/opencode.json."""
        ag_lsp_entry = McpServerEntry(
            name="ag-lsp",
            command="python",
            args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
            env={},
        )
        desired_entries = {
            "coding-lsp/ag-lsp": ("ag-lsp", ag_lsp_entry),
        }
        managed_ids = {"coding-lsp/ag-lsp"}

        sync_managed_provider_mcp_subset(
            provider_id="opencode",
            project_root=tmp_path,
            desired_entries=desired_entries,
            managed_ids=managed_ids,
        )

        opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
        data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
        servers = data.get("mcp", {})

        assert "ag-lsp" in servers
        assert "ag-lsp-mgmt" not in servers

    def test_read_write_roundtrip(self, tmp_path: Path) -> None:
        """Verify read/write roundtrip preserves entries."""
        opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"

        entries = {
            "ag-lsp": McpServerEntry(
                name="ag-lsp",
                command="python",
                args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
                env={"FOO": "bar"},
            ),
        }
        write_opencode_mcp(opencode_cfg_path, entries)

        read_entries = read_opencode_mcp(opencode_cfg_path)

        assert "ag-lsp" in read_entries
        assert read_entries["ag-lsp"].command == "python"
        assert read_entries["ag-lsp"].args == ("-m", "audiagentic.components.coding_lsp.lsp_mcp")
        assert read_entries["ag-lsp"].env == {"FOO": "bar"}

    def test_opencode_descriptor_has_mcp_config(self) -> None:
        """The real opencode descriptor should have mcp_config configured."""
        from audiagentic.components.providers.descriptors.registry import get_descriptor

        desc = get_descriptor("opencode")
        assert desc is not None
        assert desc.mcp_config is not None
        assert desc.receive_lsp_mcp is True

    def test_multiple_entries_projected_together(self, tmp_path: Path) -> None:
        """Multiple MCP entries should all be projected to opencode."""
        entries = {
            "coding-lsp/ag-lsp": ("ag-lsp", McpServerEntry(
                name="ag-lsp",
                command="python",
                args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
                env={},
            )),
            "other-component/some-mcp": ("some-mcp", McpServerEntry(
                name="some-mcp",
                command="node",
                args=("server.js",),
                env={"NODE_ENV": "production"},
            )),
        }
        managed_ids = {"coding-lsp/ag-lsp", "other-component/some-mcp"}

        result = sync_managed_provider_mcp_subset(
            provider_id="opencode",
            project_root=tmp_path,
            desired_entries=entries,
            managed_ids=managed_ids,
        )

        assert result["ok"] is True

        opencode_cfg_path = tmp_path / ".opencode" / "opencode.json"
        data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
        servers = data.get("mcp", {})

        assert "ag-lsp" in servers
        assert "some-mcp" in servers
        assert servers["some-mcp"]["command"][0] == "node"
        assert servers["some-mcp"]["command"][1:] == ["server.js"]
        assert servers["some-mcp"]["environment"] == {"NODE_ENV": "production"}
