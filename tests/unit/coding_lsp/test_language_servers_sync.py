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
    called: list[object] = []
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_projection.sync_language_servers_to_provider_configs",
        lambda root, servers: called.append((root, servers)) or {"ok": True},
    )
    result = sync_language_servers_to_providers(tmp_path)
    assert result["synced"] == []
    assert result["skipped"] == "no valid configured language servers"
    assert called == []


def test_sync_writes_real_entries(tmp_path: Path, monkeypatch) -> None:
    _enable_python(tmp_path, settings={"python": {"analysis": "basic"}})
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_projection.sync_language_servers_to_provider_configs",
        lambda root, servers: captured.update({"root": root, "servers": servers}) or {"ok": True, "synced": ["codex"]},
    )

    result = sync_language_servers_to_providers(tmp_path)

    assert result["synced"] == ["codex"]
    assert captured["root"] == tmp_path
    entries = captured["servers"]
    assert "python" in entries
    assert entries["python"].command == ["pyright-langserver", "--stdio"]
    assert entries["python"].file_extensions == [".py", ".pyi"]


def test_prune_requests_full_catalog(tmp_path: Path, monkeypatch) -> None:
    # Disable/uninstall prunes every supported language (not just currently-active
    # ones), so previously-projected entries are never orphaned when feature state
    # has already been cleared.
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_projection.prune_language_servers_from_provider_configs",
        lambda root, languages: captured.update({"root": root, "languages": languages}) or {
            "ok": True,
            "pruned": ["codex"],
            "details": {"codex": {"removed": languages}},
        },
    )

    result = prune_language_servers_from_providers(tmp_path)

    catalog = set(language_registry.all_languages())
    assert result["pruned"] == ["codex"]
    assert "python" in catalog
    assert set(captured["languages"]) == catalog
    assert set(result["details"]["codex"]["removed"]) == catalog


def test_prune_requests_catalog_regardless_of_active_state(tmp_path: Path, monkeypatch) -> None:
    # No languages enabled in feature state, but prune still targets the whole
    # catalog; the per-provider removers are idempotent no-ops when absent.
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_projection.prune_language_servers_from_provider_configs",
        lambda root, languages: captured.update({"root": root, "languages": languages}) or {
            "ok": True,
            "pruned": [],
            "languages": languages,
        },
    )
    result = prune_language_servers_from_providers(tmp_path)
    catalog = set(language_registry.all_languages())
    assert set(result["languages"]) == catalog
    assert set(captured["languages"]) == catalog


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
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_projection.sync_generic_lsp_mcp_to_provider_configs",
        lambda root, desired_entries, managed_ids: captured.update({
            "root": root,
            "desired_entries": desired_entries,
            "managed_ids": managed_ids,
        }) or {"ok": True, "synced": ["codex"]},
    )
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync.shutil.which",
        lambda command: None,
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["synced"] == ["codex"]
    assert result["mcp_command_status"] == {
        "commands": ["custom-lsp"],
        "missing": ["custom-lsp"],
        "ok": False,
    }
    assert captured["root"] == tmp_path
    assert captured["managed_ids"] == {"coding-lsp/custom-lsp"}
    managed_id, entry = next(iter(captured["desired_entries"].items()))
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
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_projection.prune_generic_lsp_mcp_from_provider_configs",
        lambda root, managed_ids: captured.update({"root": root, "managed_ids": managed_ids}) or {
            "ok": True,
            "pruned": ["codex"],
            "managed_ids": managed_ids,
        },
    )

    result = prune_generic_lsp_mcp_from_providers(tmp_path)

    assert result["managed_ids"] == {"coding-lsp/custom-lsp"}
    assert captured["root"] == tmp_path
