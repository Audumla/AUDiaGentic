from __future__ import annotations

from pathlib import Path

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


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


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
    published: list[dict] = []
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.append(payload) or payload["default"],
    )
    result = sync_language_servers_to_providers(tmp_path)
    assert result["synced"] == []
    assert result["skipped"] == "no valid configured language servers"
    assert published == []


def test_sync_writes_real_entries(tmp_path: Path, monkeypatch) -> None:
    _enable_python(tmp_path, settings={"python": {"analysis": "basic"}})
    published: dict[str, object] = {}
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.update(payload) or {"ok": True, "synced": ["codex"]},
    )

    result = sync_language_servers_to_providers(tmp_path)

    assert result["synced"] == ["codex"]
    assert published["action"] == "sync-language-servers"
    entries = published["servers"]
    assert entries["python"].command == ["pyright-langserver", "--stdio"]
    assert entries["python"].file_extensions == [".py", ".pyi"]


def test_prune_requests_full_catalog(tmp_path: Path, monkeypatch) -> None:
    # Disable/uninstall prunes every supported language (not just currently-active
    # ones), so previously-projected entries are never orphaned when feature state
    # has already been cleared.
    published: dict[str, object] = {}
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.update(payload) or {
            "ok": True,
            "pruned": ["codex"],
            "details": {"codex": {"removed": payload["languages"]}},
        },
    )

    result = prune_language_servers_from_providers(tmp_path)

    catalog = set(language_registry.all_languages())
    assert result["pruned"] == ["codex"]
    assert published["action"] == "prune-language-servers"
    assert "python" in catalog
    assert set(published["languages"]) == catalog
    assert set(result["details"]["codex"]["removed"]) == catalog


def test_prune_requests_catalog_regardless_of_active_state(tmp_path: Path, monkeypatch) -> None:
    # No languages enabled in feature state, but prune still targets the whole
    # catalog; the per-provider removers are idempotent no-ops when absent.
    published: dict[str, object] = {}
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.update(payload) or {
            "ok": True,
            "pruned": [],
            "languages": payload["languages"],
        },
    )
    result = prune_language_servers_from_providers(tmp_path)
    catalog = set(language_registry.all_languages())
    assert set(result["languages"]) == catalog
    assert set(published["languages"]) == catalog


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
    published: dict[str, object] = {}
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.update(payload) or {"ok": True, "synced": ["codex"]},
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["synced"] == ["codex"]
    assert published["action"] == "sync-generic-mcp"
    assert published["managed_ids"] == {"coding-lsp/custom-lsp"}
    managed_id, entry = next(iter(published["desired_entries"].items()))
    assert managed_id == "coding-lsp/custom-lsp"
    assert entry[0] == "custom-lsp"
    assert entry[1].command == "custom-lsp"
    assert entry[1].args == ("serve", "--stdio")


def test_prune_generic_mcp_uses_descriptor_managed_ids(tmp_path: Path, monkeypatch) -> None:
    feature_registry.register(
        ImplementationDescriptor(
            parent="coding-lsp",
            implementation_id="custom-lsp",
            raw={"projection": {"generic-mcp": {"managed-id": "coding-lsp/custom-lsp"}}},
        )
    )
    published: dict[str, object] = {}
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.update(payload) or {
            "ok": True,
            "pruned": ["codex"],
            "managed_ids": payload["managed_ids"],
        },
    )

    result = prune_generic_lsp_mcp_from_providers(tmp_path)

    assert result["managed_ids"] == {"coding-lsp/custom-lsp"}
    assert published["action"] == "prune-generic-mcp"
