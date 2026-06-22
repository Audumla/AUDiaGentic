"""Internal providers service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


def list_providers(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.status import build_provider_status
    return build_provider_status(project_root, include_probes=False)


def get_provider_status(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.status import build_provider_status
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        payload = build_provider_status(project_root, provider_id, include_probes=True)
    except AudiaGenticError as exc:
        return {"provider_id": provider_id, "ok": False, "error": exc.message}
    providers = payload.get("providers", [])
    if providers:
        provider = providers[0]
        if isinstance(provider, dict):
            return provider
    return {"provider_id": provider_id, "ok": False, "error": "provider status unavailable"}


def list_provider_descriptors() -> list[dict[str, Any]]:
    from audiagentic.components.providers.descriptors import all_descriptors

    return [
        {
            "provider_id": descriptor.provider_id,
            "display_name": descriptor.display_name,
            "description": descriptor.description,
            "url": descriptor.url,
            "prompt_aliases": list(descriptor.prompt_aliases),
            "has_cli": descriptor.cli_probe is not None,
            "cli_probe": descriptor.cli_probe,
            "supports_catalog_fetch": descriptor.fetch_catalog_fn is not None,
            "host_capabilities": [
                {
                    "host": capability.host,
                    "capability_id": capability.capability_id,
                    "display_name": capability.display_name,
                }
                for capability in descriptor.host_capabilities
            ],
            "vscode_extensions": [
                {"extension_id": extension.capability_id, "display_name": extension.display_name}
                for extension in descriptor.vscode_extensions
            ],
            "permissions": {
                "can_write_files": descriptor.permissions.can_write_files,
                "can_execute_shell": descriptor.permissions.can_execute_shell,
                "can_browse_web": descriptor.permissions.can_browse_web,
                "can_read_env": descriptor.permissions.can_read_env,
                "notes": descriptor.permissions.notes,
            },
            "agent_files": [
                {"rel_path": agent_file.rel_path, "managed": agent_file.managed, "description": agent_file.description}
                for agent_file in descriptor.agent_files
            ],
        }
        for descriptor in sorted(all_descriptors().values(), key=lambda item: item.provider_id)
    ]


def list_provider_models(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.provider_catalog import (
        read_model_catalog,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        catalog = read_model_catalog(project_root, provider_id)
    except AudiaGenticError:
        return {"provider_id": provider_id, "models": [], "error": "no catalog found"}

    models = [
        {
            "model_id": model.get("model-id", ""),
            "display_name": model.get("display-name", ""),
            "status": model.get("status", ""),
            "supports_structured_output": model.get("supports-structured-output", False),
            "context_window": model.get("context-window", 0),
        }
        for model in catalog.get("models", [])
    ]
    return {
        "provider_id": provider_id,
        "fetched_at": catalog.get("fetched-at", ""),
        "models": models,
    }


async def refresh_provider_catalog(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.catalog import fetch_provider_catalog

    try:
        return await asyncio.to_thread(fetch_provider_catalog, provider_id, project_root=project_root)
    except Exception as exc:  # noqa: BLE001
        return {"provider_id": provider_id, "ok": False, "error": str(exc)}


async def refresh_all_catalogs(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.catalog import (
        refresh_all_catalogs as _refresh,
    )

    return await asyncio.to_thread(_refresh, project_root=project_root)


async def install_provider(project_root: Path, provider_id: str, *, dry_run: bool) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle import install_provider_cli

    return await asyncio.to_thread(
        install_provider_cli, provider_id, dry_run=dry_run, project_root=project_root
    )


async def uninstall_provider(project_root: Path, provider_id: str, *, dry_run: bool) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle import uninstall_provider_cli

    return await asyncio.to_thread(
        uninstall_provider_cli, provider_id, dry_run=dry_run, project_root=project_root
    )


async def repair_provider(project_root: Path, provider_id: str, *, dry_run: bool) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle import repair_provider_cli

    return await asyncio.to_thread(
        repair_provider_cli, provider_id, dry_run=dry_run, project_root=project_root
    )


async def apply_provider_surfaces(project_root: Path, provider_id: str | None = None) -> dict[str, Any]:
    from audiagentic.components.providers.surfaces.manager import (
        apply_provider_surfaces as _apply,
    )

    return await asyncio.to_thread(_apply, project_root, provider_id=provider_id)


async def prune_provider_surfaces(project_root: Path, provider_id: str | None = None) -> dict[str, Any]:
    from audiagentic.components.providers.surfaces.manager import (
        prune_provider_surfaces as _prune,
    )

    return await asyncio.to_thread(_prune, project_root, provider_id=provider_id)


async def reconcile_provider(project_root: Path, provider_id: str, *, fetch_catalog: bool) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle import (
        reconcile_provider as _reconcile,
    )

    return await asyncio.to_thread(
        _reconcile, provider_id, project_root=project_root, fetch_catalog=fetch_catalog
    )


async def reconcile_all_providers(project_root: Path, *, fetch_catalogs: bool) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle import (
        reconcile_all_providers as _reconcile_all,
    )

    return await asyncio.to_thread(
        _reconcile_all, project_root=project_root, fetch_catalogs=fetch_catalogs
    )
