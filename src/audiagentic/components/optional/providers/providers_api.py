"""Internal providers service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.output import ComponentOutputEvent


def list_providers(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.status import build_provider_status
    return build_provider_status(project_root, include_probes=False)


def get_provider_status(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.status import build_provider_status
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
    from audiagentic.components.optional.providers.descriptors import all_descriptors

    return [
        {
            "provider_id": descriptor.provider_id,
            "display_name": descriptor.display_name,
            "description": descriptor.description,
            "url": descriptor.url,
            "has_cli": descriptor.cli_probe is not None,
            "cli_probe": descriptor.cli_probe,
            "supports_catalog_fetch": descriptor.fetch_catalog_fn is not None,
            "vscode_extensions": [
                {"extension_id": extension.extension_id, "display_name": extension.display_name}
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
    from audiagentic.components.optional.providers.services.provider_catalog import (
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


async def refresh_provider_catalog(project_root: Path, provider_id: str, *, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.catalog import fetch_provider_catalog

    try:
        return await run_with_output(
            ctx=ctx,
            logger="providers.catalog",
            heartbeat_message=f"[{provider_id}] catalog fetch running...",
            work=lambda output: fetch_provider_catalog(provider_id, project_root=project_root, on_progress=output),
        )
    except Exception as exc:  # noqa: BLE001
        return {"provider_id": provider_id, "ok": False, "error": str(exc)}


async def refresh_all_catalogs(project_root: Path, *, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.catalog import (
        refresh_all_catalogs as _refresh,
    )

    return await run_with_output(
        ctx=ctx,
        logger="providers.catalog",
        heartbeat_message="Fetching provider catalogs...",
        work=lambda output: _refresh(project_root=project_root, on_progress=output),
    )


async def install_provider(project_root: Path, provider_id: str, *, dry_run: bool, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.lifecycle import install_provider_cli

    return await run_with_output(
        ctx=ctx,
        logger="providers.install",
        heartbeat_message=f"[{provider_id}] install still running...",
        work=lambda output: install_provider_cli(
            provider_id,
            dry_run=dry_run,
            project_root=project_root,
            on_progress=_prefix_output(provider_id, output),
        ),
    )


async def uninstall_provider(project_root: Path, provider_id: str, *, dry_run: bool, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.lifecycle import uninstall_provider_cli

    return await run_with_output(
        ctx=ctx,
        logger="providers.uninstall",
        heartbeat_message=f"[{provider_id}] uninstall still running...",
        work=lambda output: uninstall_provider_cli(
            provider_id,
            dry_run=dry_run,
            project_root=project_root,
            on_progress=_prefix_output(provider_id, output),
        ),
    )


async def repair_provider(project_root: Path, provider_id: str, *, dry_run: bool, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.lifecycle import repair_provider_cli

    return await run_with_output(
        ctx=ctx,
        logger="providers.repair",
        heartbeat_message=f"[{provider_id}] repair still running...",
        work=lambda output: repair_provider_cli(
            provider_id,
            dry_run=dry_run,
            project_root=project_root,
            on_progress=_prefix_output(provider_id, output),
        ),
    )


async def apply_provider_surfaces(project_root: Path, provider_id: str | None = None, *, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.surfaces.manager import (
        apply_provider_surfaces as _apply,
    )

    return await run_with_output(
        ctx=ctx,
        logger="providers.surfaces",
        heartbeat_message="Applying provider surfaces...",
        work=lambda output: _apply(project_root, provider_id=provider_id, on_progress=output),
    )


async def prune_provider_surfaces(project_root: Path, provider_id: str | None = None, *, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.surfaces.manager import (
        prune_provider_surfaces as _prune,
    )

    return await run_with_output(
        ctx=ctx,
        logger="providers.surfaces",
        heartbeat_message="Pruning provider surfaces...",
        work=lambda output: _prune(project_root, provider_id=provider_id, on_progress=output),
    )


async def reconcile_provider(project_root: Path, provider_id: str, *, fetch_catalog: bool, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.lifecycle import (
        reconcile_provider as _reconcile,
    )

    return await run_with_output(
        ctx=ctx,
        logger="providers.reconcile",
        heartbeat_message=f"[{provider_id}] reconcile still running...",
        work=lambda output: _reconcile(provider_id, project_root=project_root, fetch_catalog=fetch_catalog, on_progress=output),
    )


async def reconcile_all_providers(project_root: Path, *, fetch_catalogs: bool, ctx, run_with_output) -> dict[str, Any]:
    from audiagentic.components.optional.providers.services.lifecycle import (
        reconcile_all_providers as _reconcile_all,
    )

    return await run_with_output(
        ctx=ctx,
        logger="providers.reconcile",
        heartbeat_message="Reconciling providers...",
        work=lambda output: _reconcile_all(project_root=project_root, fetch_catalogs=fetch_catalogs, on_progress=output),
    )


def _prefix_output(provider_id: str, output):
    if output is None:
        return None

    def sink(event: ComponentOutputEvent) -> None:
        output(ComponentOutputEvent(
            message=f"[{provider_id}] {event.message}",
            kind=event.kind,
            level=event.level,
            progress=event.progress,
            total=event.total,
            logger=event.logger,
            data=event.data,
        ))

    return sink
