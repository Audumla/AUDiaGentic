from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.services import mcp_projection
from audiagentic.foundation.components.base import ComponentDescriptor, McpServerDeclaration
from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers


def test_provider_component_mcp_projection_uses_audiagentic_mcp(monkeypatch, tmp_path: Path) -> None:
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
    provider = type("Provider", (), {"provider_id": "fake", "mcp_config": object(), "receive_lsp_mcp": True})()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(mcp_projection, "get_descriptor", lambda component_id: descriptor)
    monkeypatch.setattr(mcp_projection, "resolve_active_provider_features", lambda root: [type("Resolved", (), {"provider_id": "fake", "kind": "mcp"})()])
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
    assert entry.command == "audiagentic"
    assert entry.args == ("mcp", "audiagentic.components.sample.sample_mcp", "--flag")
    assert entry.env == {}


def test_harness_mcp_collector_uses_audiagentic_mcp(monkeypatch, tmp_path: Path) -> None:
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
    assert entry.command == "audiagentic"
    assert entry.args == ("mcp", "audiagentic.components.sample.sample_mcp", "--flag")
    assert entry.env == {}
