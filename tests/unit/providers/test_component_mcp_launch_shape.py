from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.mcp import mcp_projection
from audiagentic.foundation.components.base import ComponentDescriptor, McpServerDeclaration
from audiagentic.foundation.mcp.launch import mcp_interpreter
from audiagentic.foundation.mcp.projection import collect_component_mcp_entries


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
    monkeypatch.setattr(mcp_projection, "is_provider_enabled", lambda root, provider_id: True)

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
    monkeypatch.setattr(mcp_projection, "is_provider_enabled", lambda root, provider_id: True)

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


def test_provider_mcp_projection_skips_disabled_providers(monkeypatch, tmp_path: Path) -> None:
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
    enabled_provider = type("Provider", (), {"provider_id": "enabled", "mcp_config": object()})()
    disabled_provider = type("Provider", (), {"provider_id": "disabled", "mcp_config": object()})()
    projected: list[str] = []

    monkeypatch.setattr(mcp_projection, "get_descriptor", lambda component_id: descriptor)
    monkeypatch.setattr(
        mcp_projection,
        "all_descriptors",
        lambda: {"enabled": enabled_provider, "disabled": disabled_provider},
    )
    monkeypatch.setattr(
        mcp_projection,
        "is_provider_enabled",
        lambda root, provider_id: provider_id == "enabled",
    )
    monkeypatch.setattr(mcp_projection, "load_managed_mcp_registry", lambda root: {})
    monkeypatch.setattr(
        mcp_projection,
        "sync_managed_provider_mcp_subset",
        lambda **kwargs: projected.append(kwargs["provider_id"]) or {"ok": True},
    )

    mcp_projection.sync_component_mcp_to_providers("sample", tmp_path, enabled=True)

    assert projected == ["enabled"]


def test_disabled_component_cleanup_still_visits_disabled_providers(
    monkeypatch, tmp_path: Path
) -> None:
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
    providers = {
        "enabled": type("Provider", (), {"provider_id": "enabled", "mcp_config": object()})(),
        "disabled": type("Provider", (), {"provider_id": "disabled", "mcp_config": object()})(),
    }
    projected: list[tuple[str, dict]] = []

    monkeypatch.setattr(mcp_projection, "get_descriptor", lambda component_id: descriptor)
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: providers)
    monkeypatch.setattr(mcp_projection, "is_provider_enabled", lambda root, provider_id: False)
    monkeypatch.setattr(
        mcp_projection,
        "load_managed_mcp_registry",
        lambda root: {"enabled": {"sample/ag-sample": "ag-sample"}},
    )
    monkeypatch.setattr(
        mcp_projection,
        "sync_managed_provider_mcp_subset",
        lambda **kwargs: projected.append((kwargs["provider_id"], kwargs["desired_entries"]))
        or {"ok": True},
    )

    mcp_projection.sync_component_mcp_to_providers("sample", tmp_path, enabled=False)

    assert [provider_id for provider_id, _ in projected] == ["enabled", "disabled"]
    assert all(not desired for _, desired in projected)


def test_disabled_provider_with_stale_entries_is_pruned_during_active_sync(
    monkeypatch, tmp_path: Path
) -> None:
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
    providers = {
        "disabled": type("Provider", (), {"provider_id": "disabled", "mcp_config": object()})(),
    }
    calls: list[dict] = []

    monkeypatch.setattr(mcp_projection, "get_descriptor", lambda component_id: descriptor)
    monkeypatch.setattr(mcp_projection, "all_descriptors", lambda: providers)
    monkeypatch.setattr(mcp_projection, "is_provider_enabled", lambda root, provider_id: False)
    monkeypatch.setattr(
        mcp_projection,
        "load_managed_mcp_registry",
        lambda root: {"disabled": {"sample/ag-sample": "ag-sample"}},
    )
    monkeypatch.setattr(
        mcp_projection,
        "sync_managed_provider_mcp_subset",
        lambda **kwargs: calls.append(kwargs) or {"ok": True},
    )

    mcp_projection.sync_component_mcp_to_providers("sample", tmp_path, enabled=True)

    assert len(calls) == 1
    assert calls[0]["provider_id"] == "disabled"
    assert calls[0]["desired_entries"] == {}
    assert calls[0]["managed_ids"] == {"sample/ag-sample"}


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

    monkeypatch.setattr("audiagentic.foundation.mcp.projection.all_descriptors", lambda: {"sample": descriptor})

    servers = collect_component_mcp_entries(
        tmp_path,
        propagation_target="audiagentic",
        require_enabled=False,
    )

    entry = servers["ag-sample"]
    assert entry.command == mcp_interpreter()
    assert entry.args == ("-m", "audiagentic.launcher", "mcp", "audiagentic.components.sample.sample_mcp", "--flag")
    assert entry.env == {"AUDIAGENTIC_REPO_ROOT": str(tmp_path.resolve())}
