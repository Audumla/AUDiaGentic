from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.optional.coding_lsp.language_servers import LanguageServerEntry
from audiagentic.foundation.mcp import McpServerEntry

from ..descriptors.registry import all_descriptors
from .feature_resolution import enabled_provider_ids
from .mcp import sync_managed_provider_mcp_subset

logger = logging.getLogger(__name__)

CODING_LSP_PROVIDER_PROJECTION = "coding-lsp.provider-projection.*"
CODING_LSP_PROVIDER_SYNC = "coding-lsp.provider-projection.sync"


def sync_language_servers_to_provider_configs(
    project_root: Path,
    servers_to_write: dict[str, LanguageServerEntry],
) -> dict[str, Any]:
    if not servers_to_write:
        return {"ok": True, "synced": [], "skipped": "no valid configured language servers"}

    results: dict[str, dict[str, Any]] = {}
    synced: list[str] = []
    skipped: list[str] = []
    enabled = enabled_provider_ids(project_root)
    languages = list(servers_to_write.keys())

    for descriptor in all_descriptors().values():
        spec = descriptor.language_servers_config
        if spec is None:
            skipped.append(descriptor.provider_id)
            continue
        try:
            config_path = spec.config_path
            if callable(config_path):
                config_path = config_path(project_root)
            else:
                config_path = project_root / config_path

            if descriptor.provider_id in enabled:
                spec.writer(config_path, servers_to_write)
                synced.append(descriptor.provider_id)
                results[descriptor.provider_id] = {
                    "ok": True,
                    "config_path": str(config_path),
                    "servers_written": list(servers_to_write.keys()),
                }
            else:
                removed = [lang for lang in languages if spec.remover(config_path, lang)]
                skipped.append(descriptor.provider_id)
                results[descriptor.provider_id] = {
                    "ok": True,
                    "config_path": str(config_path),
                    "pruned": removed,
                    "reason": "provider disabled",
                }
        except Exception:
            logger.warning("Failed to sync language servers to %s", descriptor.provider_id, exc_info=True, extra={"provider": descriptor.provider_id})
            results[descriptor.provider_id] = {"ok": False, "error": "sync failed"}
            skipped.append(descriptor.provider_id)

    return {
        "ok": True,
        "synced": synced,
        "skipped": skipped,
        "servers": languages,
        "details": results,
    }


def sync_generic_lsp_mcp_to_provider_configs(
    project_root: Path,
    desired_entry: dict[str, tuple[str, McpServerEntry]],
    managed_ids: set[str],
) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    synced: list[str] = []
    skipped: list[str] = []
    enabled = enabled_provider_ids(project_root)

    for descriptor in all_descriptors().values():
        if descriptor.mcp_config is None:
            skipped.append(descriptor.provider_id)
            continue
        self_provides_lsp = (
            descriptor.language_servers_config is not None
            or descriptor.on_lsp_enabled is not None
        )
        project = descriptor.provider_id in enabled and not self_provides_lsp
        desired = desired_entry if project else {}
        result = sync_managed_provider_mcp_subset(
            provider_id=descriptor.provider_id,
            project_root=project_root,
            desired_entries=desired,
            managed_ids=managed_ids,
        )
        results[descriptor.provider_id] = result
        synced.append(descriptor.provider_id)

    return {"ok": True, "synced": synced, "skipped": skipped, "details": results}


def provision_provider_lsp_support(project_root: Path) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    provisioned: list[str] = []
    skipped: list[str] = []
    enabled = enabled_provider_ids(project_root)

    for descriptor in all_descriptors().values():
        hook = descriptor.on_lsp_enabled
        if hook is None or descriptor.provider_id not in enabled:
            skipped.append(descriptor.provider_id)
            continue
        try:
            results[descriptor.provider_id] = hook(project_root)
            provisioned.append(descriptor.provider_id)
        except Exception:
            logger.warning("Failed to provision LSP support for %s", descriptor.provider_id, exc_info=True, extra={"provider": descriptor.provider_id})
            results[descriptor.provider_id] = {"ok": False, "error": "provision failed"}

    return {"ok": True, "provisioned": provisioned, "skipped": skipped, "details": results}


def prune_language_servers_from_provider_configs(
    project_root: Path,
    languages: list[str],
) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    pruned: list[str] = []
    skipped: list[str] = []

    for descriptor in all_descriptors().values():
        spec = descriptor.language_servers_config
        if spec is None:
            skipped.append(descriptor.provider_id)
            continue
        try:
            config_path = spec.config_path
            if callable(config_path):
                config_path = config_path(project_root)
            else:
                config_path = project_root / config_path
            removed = [lang for lang in languages if spec.remover(config_path, lang)]
            pruned.append(descriptor.provider_id)
            results[descriptor.provider_id] = {
                "ok": True,
                "config_path": str(config_path),
                "removed": removed,
            }
        except Exception:
            logger.warning("Failed to prune language servers from %s", descriptor.provider_id, exc_info=True, extra={"provider": descriptor.provider_id})
            results[descriptor.provider_id] = {"ok": False, "error": "prune failed"}

    return {"ok": True, "pruned": pruned, "skipped": skipped, "languages": languages, "details": results}


def prune_generic_lsp_mcp_from_provider_configs(
    project_root: Path,
    managed_ids: set[str],
) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    pruned: list[str] = []
    skipped: list[str] = []

    for descriptor in all_descriptors().values():
        if descriptor.mcp_config is None:
            skipped.append(descriptor.provider_id)
            continue
        result = sync_managed_provider_mcp_subset(
            provider_id=descriptor.provider_id,
            project_root=project_root,
            desired_entries={},
            managed_ids=managed_ids,
        )
        results[descriptor.provider_id] = result
        pruned.append(descriptor.provider_id)

    return {"ok": True, "pruned": pruned, "skipped": skipped, "details": results}


def handle_lsp_provider_projection(event_type: str, payload: dict, metadata: dict) -> None:
    project_root = payload.get("project_root")
    action = payload.get("action")
    if not isinstance(project_root, Path) or not isinstance(action, str):
        return

    if action == "sync-language-servers":
        result = sync_language_servers_to_provider_configs(
            project_root,
            dict(payload.get("servers") or {}),
        )
    elif action == "sync-generic-mcp":
        result = sync_generic_lsp_mcp_to_provider_configs(
            project_root,
            dict(payload.get("desired_entries") or {}),
            set(payload.get("managed_ids") or ()),
        )
    elif action == "provision-support":
        result = provision_provider_lsp_support(project_root)
    elif action == "prune-language-servers":
        result = prune_language_servers_from_provider_configs(
            project_root,
            list(payload.get("languages") or []),
        )
    elif action == "prune-generic-mcp":
        result = prune_generic_lsp_mcp_from_provider_configs(
            project_root,
            set(payload.get("managed_ids") or ()),
        )
    else:
        result = {"ok": False, "error": f"unknown LSP provider projection action: {action}"}

    result_slot = payload.get("result")
    if isinstance(result_slot, dict):
        result_slot.update(result)
