from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.base import McpServerDeclaration
from audiagentic.runtime.lifecycle import components as comp


class _Provider:
    def __init__(self, provider_id: str, *, native: bool) -> None:
        self.provider_id = provider_id
        self.mcp_config = object()  # has an mcp config target
        self.language_servers_config = object() if native else None


class _Component:
    def __init__(self, servers) -> None:
        self.mcp_servers = servers
        self.external_mcp_servers = ()


def test_native_provider_skips_ag_lsp_generic_provider_keeps_it(tmp_path: Path, monkeypatch) -> None:
    ag_lsp = McpServerDeclaration(
        name="ag-lsp",
        module="audiagentic.components.optional.coding_lsp.lsp_mcp",
        propagate="providers",
        skip_if_native_lsp=True,
    )
    ag_ledger = McpServerDeclaration(
        name="ag-ledger",
        module="audiagentic.components.optional.ledger.ledger_mcp",
        propagate="providers",
        skip_if_native_lsp=False,
    )

    providers = {
        "codex": _Provider("codex", native=True),
        "claude": _Provider("claude", native=False),
    }
    captured: dict[str, list[str]] = {}

    def _fake_sync(*, provider_id, project_root, desired_entries):
        captured[provider_id] = sorted(name for name, _ in desired_entries.values())
        return {"ok": True}

    monkeypatch.setattr(
        "audiagentic.components.optional.providers.descriptors.registry.all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        "audiagentic.components.optional.providers.services.mcp.sync_managed_provider_mcp",
        _fake_sync,
    )

    comp._propagate_mcp_to_providers(_Component([ag_lsp, ag_ledger]), tmp_path)

    # native provider: ag-lsp suppressed, ledger kept
    assert captured["codex"] == ["ag-ledger"]
    # generic provider: both kept (gets generic LSP via MCP)
    assert captured["claude"] == ["ag-ledger", "ag-lsp"]
