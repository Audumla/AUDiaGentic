from __future__ import annotations

from pathlib import Path

from audiagentic.components.optional.coding_lsp.language_servers_sync import (
    prune_generic_lsp_mcp_from_providers,
    sync_generic_lsp_mcp_to_providers,
)
from audiagentic.foundation.mcp import McpServerEntry


class _Provider:
    def __init__(self, provider_id: str, *, native: bool, has_mcp: bool = True) -> None:
        self.provider_id = provider_id
        self.mcp_config = object() if has_mcp else None
        self.language_servers_config = object() if native else None
        self.on_lsp_enabled = None


def test_sync_generic_lsp_routes_by_provider_capability(tmp_path: Path, monkeypatch) -> None:
    providers = {
        "codex": _Provider("codex", native=True),
        "claude": _Provider("claude", native=False),
        "aider": _Provider("aider", native=False, has_mcp=False),
    }
    captured: dict[str, dict[str, tuple[str, McpServerEntry]]] = {}

    def _fake_sync(*, provider_id, project_root, desired_entries, managed_ids):
        captured[provider_id] = desired_entries
        assert managed_ids == {"coding-lsp/ag-lsp"}
        return {"ok": True}

    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.sync_managed_provider_mcp_subset",
        _fake_sync,
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["ok"] is True
    assert "aider" in result["skipped"]
    assert captured["codex"] == {}
    assert list(captured["claude"]) == ["coding-lsp/ag-lsp"]
    assert captured["claude"]["coding-lsp/ag-lsp"][0] == "ag-lsp"


def test_prune_generic_lsp_only_targets_component_owned_entry(tmp_path: Path, monkeypatch) -> None:
    providers = {
        "codex": _Provider("codex", native=True),
        "claude": _Provider("claude", native=False),
    }
    captured: dict[str, set[str]] = {}

    def _fake_sync(*, provider_id, project_root, desired_entries, managed_ids):
        captured[provider_id] = managed_ids
        assert desired_entries == {}
        return {"ok": True}

    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.sync_managed_provider_mcp_subset",
        _fake_sync,
    )

    result = prune_generic_lsp_mcp_from_providers(tmp_path)

    assert result["ok"] is True
    assert captured == {
        "codex": {"coding-lsp/ag-lsp"},
        "claude": {"coding-lsp/ag-lsp"},
    }
