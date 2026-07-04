from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.services import mcp_projection
from audiagentic.foundation.components.base import ComponentDescriptor, McpServerDeclaration
from audiagentic.foundation.mcp.launch import mcp_interpreter
from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers


def test_provider_component_mcp_projection_uses_audiagentic_mcp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
    descriptor = ComponentDescriptor(
        component_id="sample",
        display_name="Sample",
        description="",
        detection_marker=".sample",
        mcp_servers=(
            McpServerDeclaration(
                name="ag-sample",
                module="audiagentic.components.sample.sample_mcp",
                managed_id="sample/ag-sample",
                args=("--flag",),
                propagate="providers",
            ),
        ),
    )
    provider = type("Provider", (), {"provider_id": "fake", "mcp_config": object()})()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(mcp_projection, "get_descriptor", lambda component_id: descriptor)
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: {"fake": provider})

    def _fake_sync(*, provider_id, project_root, desired_entries, managed_ids):
        captured["desired_entries"] = desired_entries
        captured["managed_ids"] = managed_ids
        return {"ok": True}

    monkeypatch.setattr(mcp_projection, "sync_managed_provider_mcp_subset", _fake_sync)

    mcp_projection.sync_component_mcp_to_providers("sample", tmp_path)

    assert captured["managed_ids"] == {"sample/ag-sample"}
    name, entry = captured["desired_entries"]["sample/ag-sample"]
    assert name == "ag-sample"
    assert entry.command == mcp_interpreter()
    assert entry.args == ("-m", "audiagentic.launcher", "mcp", "audiagentic.components.sample.sample_mcp", "--flag")
    assert entry.env == {}


def test_mcp_entry_propagates_repo_root_override(monkeypatch) -> None:
    """AUDIAGENTIC_REPO_ROOT is forwarded into MCP server env when set."""
    from audiagentic.foundation.mcp.component_builder import entry_from_mcp_declaration

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", "X:\\somewhere\\repo")
    entry = entry_from_mcp_declaration(
        McpServerDeclaration(
            name="ag-sample",
            module="audiagentic.components.sample.sample_mcp",
        )
    )
    assert entry.env == {"AUDIAGENTIC_REPO_ROOT": "X:\\somewhere\\repo"}


def test_provider_mcp_projection_not_gated_by_receive_lsp_mcp(monkeypatch, tmp_path: Path) -> None:
    """receive_lsp_mcp is an LSP-only opt-out and must not gate component MCP projection."""
    descriptor = ComponentDescriptor(
        component_id="sample",
        display_name="Sample",
        description="",
        detection_marker=".sample",
        mcp_servers=(
            McpServerDeclaration(
                name="ag-sample",
                module="audiagentic.components.sample.sample_mcp",
                managed_id="sample/ag-sample",
                propagate="providers",
            ),
        ),
    )
    # Provider with receive_lsp_mcp=False — must still receive component MCP servers.
    provider = type("Provider", (), {"provider_id": "fake", "mcp_config": object(), "receive_lsp_mcp": False})()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(mcp_projection, "get_descriptor", lambda component_id: descriptor)
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: {"fake": provider})

    def _fake_sync(*, provider_id, project_root, desired_entries, managed_ids):
        captured["provider_id"] = provider_id
        captured["desired_entries"] = desired_entries
        return {"ok": True}

    monkeypatch.setattr(mcp_projection, "sync_managed_provider_mcp_subset", _fake_sync)

    mcp_projection.sync_component_mcp_to_providers("sample", tmp_path)

    assert captured.get("provider_id") == "fake", (
        "receive_lsp_mcp=False must not prevent component MCP projection to a provider. "
        "receive_lsp_mcp only gates the LSP-specific ag-lsp server (lsp_projection.py)."
    )
    assert "sample/ag-sample" in captured["desired_entries"]


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

    monkeypatch.setattr("audiagentic.runtime.harness.mcp_collector.register_all_components", lambda: None)
    monkeypatch.setattr("audiagentic.runtime.harness.mcp_collector.all_descriptors", lambda: {"sample": descriptor})

    servers = collect_mcp_servers(tmp_path)

    entry = servers["ag-sample"]
    assert entry.command == mcp_interpreter()
    assert entry.args == ("-m", "audiagentic.launcher", "mcp", "audiagentic.components.sample.sample_mcp", "--flag")
    assert entry.env == {}
