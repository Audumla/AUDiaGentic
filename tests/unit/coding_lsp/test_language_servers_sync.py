from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp import language_registry
from audiagentic.components.coding_lsp.language_servers_sync import (
    prune_generic_lsp_mcp_from_providers,
    prune_language_servers_from_providers,
    sync_generic_lsp_mcp_to_providers,
    sync_language_servers_to_providers,
)
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import (
    BindingDescriptor,
    FeatureState,
    ImplementationDescriptor,
)
from audiagentic.foundation.features.state import set_feature_state


def _enable_python(tmp_path: Path, *, settings: dict | None = None) -> None:
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    options = {"server-settings": settings} if settings is not None else {}
    set_feature_state(
        tmp_path,
        "coding-lsp",
        "language",
        "python",
        FeatureState(enabled=True, options=options),
    )


def test_sync_skips_when_config_missing(tmp_path: Path, monkeypatch) -> None:
    result = sync_language_servers_to_providers(tmp_path)
    assert result["synced"] == []
    assert result["skipped"] == "no valid configured language servers"


def test_sync_writes_real_entries(tmp_path: Path, monkeypatch) -> None:
    _enable_python(tmp_path, settings={"python": {"analysis": "basic"}})
    captured: list[dict[str, Any]] = []

    def fake_manage_all(project_root, *, mode, request):
        from audiagentic.components.providers.contracts.language_server_projection import (
            LanguageServerProjectionResult,
        )
        captured.append({
            "project_root": project_root,
            "mode": mode,
            "entries": dict(request.entries),
        })
        return [LanguageServerProjectionResult(
            ok=True, supported=True, provider_id="opencode"
        )]

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.manage_language_servers_all",
        fake_manage_all,
    )

    result = sync_language_servers_to_providers(tmp_path)

    assert result["synced"] == ["opencode"]
    assert len(captured) == 1
    entries = captured[0]["entries"]
    assert "python" in entries
    assert entries["python"].command == ["pyright-langserver", "--stdio"]
    assert entries["python"].file_extensions == [".py", ".pyi"]


def test_prune_requests_full_catalog(tmp_path: Path, monkeypatch) -> None:
    # Disable/uninstall prunes every supported language (not just currently-active
    # ones), so previously-projected entries are never orphaned when feature state
    # has already been cleared.
    captured: list[dict[str, Any]] = []

    def fake_manage_all(project_root, *, mode, request):
        from audiagentic.components.providers.contracts.language_server_projection import (
            LanguageServerProjectionResult,
        )
        captured.append({"mode": mode, "entries": dict(request.entries)})
        return [LanguageServerProjectionResult(
            ok=True, supported=True, provider_id="opencode"
        )]

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.manage_language_servers_all",
        fake_manage_all,
    )

    prune_language_servers_from_providers(tmp_path)

    catalog = set(language_registry.all_languages())
    assert "python" in catalog
    # Verify all languages were sent in prune requests
    for call in captured:
        assert call["mode"] == "prune"
        assert set(call["entries"]) == catalog


def test_prune_requests_catalog_regardless_of_active_state(tmp_path: Path, monkeypatch) -> None:
    # No languages enabled in feature state, but prune still targets the whole
    # catalog; the per-provider removers are idempotent no-ops when absent.
    captured: list[dict[str, Any]] = []

    def fake_manage_all(project_root, *, mode, request):
        from audiagentic.components.providers.contracts.language_server_projection import (
            LanguageServerProjectionResult,
        )
        captured.append({"mode": mode, "entries": dict(request.entries)})
        return [LanguageServerProjectionResult(
            ok=True, supported=True, provider_id="opencode"
        )]

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.manage_language_servers_all",
        fake_manage_all,
    )

    prune_language_servers_from_providers(tmp_path)
    catalog = set(language_registry.all_languages())
    # Verify all languages were sent in prune requests
    for call in captured:
        assert set(call["entries"]) == catalog


def test_generic_mcp_projection_uses_implementation_descriptor(tmp_path: Path, monkeypatch) -> None:
    feature_registry.register(
        ImplementationDescriptor(
            parent="coding-lsp",
            implementation_id="custom-lsp",
            raw={
                "projection": {
                    "generic-mcp": {
                        "managed-id": "coding-lsp/custom-lsp",
                        "name": "custom-lsp",
                        "command": "custom-lsp",
                        "args": ["serve", "--stdio"],
                    }
                }
            },
        )
    )
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="custom-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="custom-lsp.generic-mcp",
        )
    )
    set_feature_state(tmp_path, "coding-lsp", "language", "python", FeatureState(enabled=True))
    captured: dict[str, Any] = {}

    def fake_manage_all(project_root, *, mode, request):
        from audiagentic.components.providers.contracts.managed_mcp import (
            ManagedMcpResult,
        )
        captured.update({
            "root": project_root,
            "mode": mode,
            "ownership_scope": request.ownership_scope,
            "entries": list(request.entries),
        })
        return [ManagedMcpResult(ok=True, supported=True)]

    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync.manage_mcp_entries_all",
        fake_manage_all,
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["synced"] == [""]
    assert captured["root"] == tmp_path
    assert captured["mode"] == "apply"
    assert captured["ownership_scope"] == "coding-lsp/ag-lsp"
    entry = captured["entries"][0]
    assert entry.managed_id == "coding-lsp/custom-lsp"
    assert entry.name == "custom-lsp"
    assert entry.command == "custom-lsp"
    assert entry.args == ("serve", "--stdio")


def test_prune_generic_mcp_uses_scope(tmp_path: Path, monkeypatch) -> None:
    feature_registry.register(
        ImplementationDescriptor(
            parent="coding-lsp",
            implementation_id="custom-lsp",
            raw={"projection": {"generic-mcp": {"managed-id": "coding-lsp/custom-lsp"}}},
        )
    )
    captured: dict[str, Any] = {}

    def fake_manage_all(project_root, *, mode, request):
        from audiagentic.components.providers.contracts.managed_mcp import (
            ManagedMcpResult,
        )
        captured.update({
            "root": project_root,
            "mode": mode,
            "ownership_scope": request.ownership_scope,
            "entries": list(request.entries),
        })
        return [ManagedMcpResult(ok=True, supported=True)]

    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync.manage_mcp_entries_all",
        fake_manage_all,
    )

    result = prune_generic_lsp_mcp_from_providers(tmp_path)

    assert result["pruned"] == [""]
    assert captured["mode"] == "prune"
    assert captured["ownership_scope"] == "coding-lsp/ag-lsp"
    assert not captured["entries"]
    assert captured["root"] == tmp_path
