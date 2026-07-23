"""Management projection gating: audiagentic-propagated servers must be
available on install alone — not install+enabled, which would be circular
(you need the mgmt tool reachable to enable the component in the first
place). Contrast with providers-propagated servers, gated on install-to-sync +
enabled-to-populate in components/providers/services/mcp_sync.py.
"""
from __future__ import annotations

import pytest

from audiagentic.foundation.components.base import ComponentDescriptor, McpServerDeclaration
from audiagentic.foundation.contracts.error_resolutions import load_all_error_resolutions
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp import projection as mcp_projection


def _management_entries(project_root):
    return mcp_projection.collect_component_mcp_entries(
        project_root,
        propagation_target="audiagentic",
        require_enabled=False,
    )


def _descriptor(component_id: str, *, core: bool = False) -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=component_id,
        display_name=component_id,
        description="",
        detection_marker="marker.yaml",
        core=core,
        mcp_servers=(
            McpServerDeclaration(
                name=f"ag-{component_id}-mgmt",
                module=f"audiagentic.components.{component_id}.mgmt",
                propagate="audiagentic",
            ),
        ),
    )


def test_mgmt_server_available_when_installed_but_not_enabled(monkeypatch, tmp_path) -> None:
    # Installed-but-disabled must still expose its mgmt tool — otherwise there is
    # no way to reach the tool that would enable it.
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: {"widgets": _descriptor("widgets")})
    monkeypatch.setattr(mcp_projection, "is_installed", lambda _cid, _root: True)
    monkeypatch.setattr(mcp_projection, "get_external_probe_results", lambda _cid, _root: {})

    servers = _management_entries(tmp_path)
    assert "ag-widgets-mgmt" in servers


def test_mgmt_server_absent_when_not_installed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: {"widgets": _descriptor("widgets")})
    monkeypatch.setattr(mcp_projection, "is_installed", lambda _cid, _root: False)
    monkeypatch.setattr(mcp_projection, "get_external_probe_results", lambda _cid, _root: {})

    servers = _management_entries(tmp_path)
    assert "ag-widgets-mgmt" not in servers


def test_core_component_mgmt_server_available_without_install_marker(monkeypatch, tmp_path) -> None:
    # Core components are conceptually always "installed" for mgmt purposes.
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: {"project": _descriptor("project", core=True)})
    monkeypatch.setattr(mcp_projection, "is_installed", lambda _cid, _root: False)
    monkeypatch.setattr(mcp_projection, "get_external_probe_results", lambda _cid, _root: {})

    servers = _management_entries(tmp_path)
    assert "ag-project-mgmt" in servers


def test_functional_projection_requires_enabled(monkeypatch, tmp_path) -> None:
    descriptor = ComponentDescriptor(
        component_id="widgets",
        display_name="widgets",
        description="",
        detection_marker="marker.yaml",
        mcp_servers=(
            McpServerDeclaration(
                name="ag-widgets",
                module="audiagentic.components.widgets.tools",
                propagate="providers",
            ),
        ),
    )
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: {"widgets": descriptor})
    monkeypatch.setattr(mcp_projection, "is_installed", lambda _cid, _root: True)
    monkeypatch.setattr(mcp_projection, "is_enabled", lambda _cid, _root: False)
    monkeypatch.setattr(mcp_projection, "get_external_probe_results", lambda _cid, _root: {})

    assert mcp_projection.collect_component_mcp_entries(
        tmp_path, propagation_target="providers", require_enabled=True
    ) == {}

    monkeypatch.setattr(mcp_projection, "is_enabled", lambda _cid, _root: True)
    assert "ag-widgets" in mcp_projection.collect_component_mcp_entries(
        tmp_path, propagation_target="providers", require_enabled=True
    )


def test_conflicting_projection_uses_registered_canonical_error() -> None:
    load_all_error_resolutions()
    servers: dict[str, McpServerEntry] = {}
    mcp_projection._add_entry(servers, McpServerEntry(name="same", command="first"))

    with pytest.raises(AudiaGenticError) as caught:
        mcp_projection._add_entry(servers, McpServerEntry(name="same", command="second"))

    assert caught.value.code == "VAL-MCPPRJ-001"
    assert caught.value.kind == "mcp-projection"
