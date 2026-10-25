from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.base import ComponentDescriptor, McpServerDeclaration
from audiagentic.foundation.mcp.component_builder import entry_from_mcp_declaration
from audiagentic.foundation.mcp.launch import mcp_interpreter
from audiagentic.foundation.mcp.projection import collect_component_mcp_entries


def test_native_component_entry_uses_canonical_stdio_launch(tmp_path):
    entry = entry_from_mcp_declaration(
        McpServerDeclaration(
            name="ag-sample",
            module="audiagentic.components.sample.sample_mcp",
            args=("--flag",),
            propagate="providers",
        ),
        tmp_path,
    )
    assert entry.command == mcp_interpreter()
    assert entry.args == (
        "-m",
        "audiagentic.launcher",
        "mcp",
        "audiagentic.components.sample.sample_mcp",
        "--flag",
    )
    assert entry.env == {"AUDIAGENTIC_REPO_ROOT": str(tmp_path.resolve())}


def test_mcp_entry_propagates_repo_root_override(monkeypatch) -> None:
    """AUDIAGENTIC_REPO_ROOT is forwarded into MCP server env when set."""
    from audiagentic.foundation.mcp.component_builder import entry_from_mcp_declaration

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", "X:\\somewhere\\repo")
    entry = entry_from_mcp_declaration(
        McpServerDeclaration(
            name="ag-sample",
            module="audiagentic.components.sample.sample_mcp",
        ),
        Path("X:/somewhere/repo"),
    )
    assert entry.env == {"AUDIAGENTIC_REPO_ROOT": str(Path("X:/somewhere/repo").resolve())}


def test_harness_mcp_collector_uses_audiagentic_mcp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
    descriptor = ComponentDescriptor(
        component_id="sample",
        display_name="Sample",
        description="",
        detection_marker=".sample",
        core=True,
        mcp_servers=(
            McpServerDeclaration(
                name="ag-sample",
                module="audiagentic.components.sample.sample_mcp",
                args=("--flag",),
            ),
        ),
    )

    monkeypatch.setattr(
        "audiagentic.foundation.mcp.projection.all_descriptors", lambda: {"sample": descriptor}
    )

    servers = collect_component_mcp_entries(
        tmp_path,
        propagation_target="audiagentic",
        require_enabled=False,
    )

    entry = servers["ag-sample"]
    assert entry.command == mcp_interpreter()
    assert entry.args == (
        "-m",
        "audiagentic.launcher",
        "mcp",
        "audiagentic.components.sample.sample_mcp",
        "--flag",
    )
    assert entry.env == {"AUDIAGENTIC_REPO_ROOT": str(tmp_path.resolve())}
