"""Language server sync from LSP component to provider configs.

When the coding-lsp component is enabled, discovers which language servers
are available on the system and writes them to each provider's config that
declares a language_servers_config spec.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
    CODING_LSP_DIR,
    load_runtime_servers,
)
from audiagentic.components.optional.providers.descriptors.base import LanguageServerEntry
from audiagentic.components.optional.providers.descriptors.registry import all_descriptors

logger = logging.getLogger(__name__)


def sync_language_servers_to_providers(project_root: Path) -> dict[str, Any]:
    """Discover available language servers and sync to all providers with language_servers_config.

    Returns summary of sync results per provider.
    """
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    try:
        configured, errors, exists = load_runtime_servers(lsp_path)
    except Exception:
        logger.warning("Failed to load language server config", exc_info=True)
        configured, errors, exists = {}, ["load failed"], lsp_path.exists()

    if errors:
        return {"ok": True, "synced": [], "skipped": "invalid lsp config", "errors": errors}
    if not exists or not configured:
        return {"ok": True, "synced": [], "skipped": "no valid configured language servers"}

    servers_to_write: dict[str, LanguageServerEntry] = {}
    for lang, server in configured.items():
        servers_to_write[lang] = LanguageServerEntry(
            language=lang,
            command=list(server.command),
            file_extensions=list(server.file_extensions),
            settings=dict(server.settings),
        )

    results: dict[str, dict[str, Any]] = {}
    synced: list[str] = []
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

            spec.writer(config_path, servers_to_write)
            synced.append(descriptor.provider_id)
            results[descriptor.provider_id] = {
                "ok": True,
                "config_path": str(config_path),
                "servers_written": list(servers_to_write.keys()),
            }
        except Exception:
            logger.warning(
                "Failed to sync language servers to %s",
                descriptor.provider_id,
                exc_info=True,
            )
            results[descriptor.provider_id] = {
                "ok": False,
                "error": "sync failed",
            }
            skipped.append(descriptor.provider_id)

    return {
        "ok": True,
        "synced": synced,
        "skipped": skipped,
        "servers": list(servers_to_write.keys()),
        "details": results,
    }


def prune_language_servers_from_providers(project_root: Path) -> dict[str, Any]:
    """Remove synced language server entries from provider configs on disable.

    Removes exactly the languages configured in lsp.json (the ones sync wrote),
    via each provider's remover. Unmanaged/user-added entries are preserved.
    If lsp.json is gone, there is nothing known to remove.
    """
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    try:
        configured, errors, exists = load_runtime_servers(lsp_path)
    except Exception:
        logger.warning("Failed to load language server config", exc_info=True)
        configured, errors, exists = {}, ["load failed"], lsp_path.exists()
    languages = list(configured.keys()) if (exists and not errors) else []

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
            logger.warning(
                "Failed to prune language servers from %s",
                descriptor.provider_id,
                exc_info=True,
            )
            results[descriptor.provider_id] = {
                "ok": False,
                "error": "prune failed",
            }

    return {
        "ok": True,
        "pruned": pruned,
        "skipped": skipped,
        "languages": languages,
        "details": results,
    }
