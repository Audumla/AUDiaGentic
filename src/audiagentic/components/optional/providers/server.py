"""AUDiaGentic providers component MCP server.

Exposes provider configuration status and runtime catalog info to the Pi TUI.
Reads AUDIAGENTIC_REPO_ROOT from env to locate the target project.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import Context
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.output import ComponentOutputEvent
from audiagentic.runtime.mcp.server import run_blocking_with_output

register_all_components()


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if not repo_root:
        raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")
    return Path(repo_root)


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


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PROVIDERS, "audiagentic-providers")


def _server_instructions() -> str:
    decl = _server_decl()
    return (
        decl.instructions
        if decl and decl.instructions
        else (
            "AUDiaGentic providers component server. "
            "Use list_providers to see all providers and their status, "
            "provider_status to inspect a specific provider's runtime catalog."
        )
    )


def _tool_description(name: str, fallback: str) -> str:
    decl = _server_decl()
    if decl and name in decl.tool_descriptions:
        return decl.tool_descriptions[name]
    return fallback


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-providers",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("list_providers", "List all known providers and their configuration or catalog status."))
    def list_providers() -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.status import build_provider_status
        return build_provider_status(_project_root())

    @mcp.tool(description=_tool_description("provider_status", "Return detailed status for a specific provider including catalog contents."))
    def provider_status(provider_id: str) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.status import build_provider_status
        from audiagentic.foundation.contracts.errors import AudiaGenticError
        try:
            return build_provider_status(_project_root(), provider_id)
        except AudiaGenticError as exc:
            return {"provider_id": provider_id, "ok": False, "error": exc.message}

    @mcp.tool(description=_tool_description("interrogate_provider", "Interrogate a provider for CLI availability, VS Code extension status, permissions, and agent files."))
    def interrogate_provider(provider_id: str) -> dict[str, Any]:
        from audiagentic.components.optional.providers.descriptors import interrogate
        project_root = _project_root()
        return interrogate(provider_id, project_root)

    @mcp.tool(description=_tool_description("list_provider_descriptors", "List all registered provider descriptors and static metadata."))
    def list_provider_descriptors() -> list[dict[str, Any]]:
        from audiagentic.components.optional.providers.descriptors import all_descriptors
        return [
            {
                "provider_id": d.provider_id,
                "display_name": d.display_name,
                "description": d.description,
                "url": d.url,
                "has_cli": d.cli_probe is not None,
                "cli_probe": d.cli_probe,
                "supports_catalog_fetch": d.fetch_catalog_fn is not None,
                "vscode_extensions": [
                    {"extension_id": e.extension_id, "display_name": e.display_name}
                    for e in d.vscode_extensions
                ],
                "permissions": {
                    "can_write_files": d.permissions.can_write_files,
                    "can_execute_shell": d.permissions.can_execute_shell,
                    "can_browse_web": d.permissions.can_browse_web,
                    "can_read_env": d.permissions.can_read_env,
                    "notes": d.permissions.notes,
                },
                "agent_files": [
                    {"rel_path": f.rel_path, "managed": f.managed, "description": f.description}
                    for f in d.agent_files
                ],
            }
            for d in sorted(all_descriptors().values(), key=lambda x: x.provider_id)
        ]

    @mcp.tool(description=_tool_description("list_provider_models", "List model IDs from a provider runtime catalog."))
    def list_provider_models(provider_id: str) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.provider_catalog import (
            read_model_catalog,
        )
        from audiagentic.foundation.contracts.errors import AudiaGenticError
        project_root = _project_root()
        try:
            catalog = read_model_catalog(project_root, provider_id)
        except AudiaGenticError:
            return {"provider_id": provider_id, "models": [], "error": "no catalog found"}
        models = [
            {
                "model_id": m.get("model-id", ""),
                "display_name": m.get("display-name", ""),
                "status": m.get("status", ""),
                "supports_structured_output": m.get("supports-structured-output", False),
                "context_window": m.get("context-window", 0),
            }
            for m in catalog.get("models", [])
        ]
        return {
            "provider_id": provider_id,
            "fetched_at": catalog.get("fetched-at", ""),
            "models": models,
        }

    @mcp.tool(description=_tool_description("refresh_provider_catalog", "Fetch and persist live model catalog for a provider."))
    async def refresh_provider_catalog(provider_id: str, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.catalog import (
            fetch_provider_catalog,
        )
        project_root = _project_root()
        try:
            return await run_blocking_with_output(
                ctx=ctx,
                logger="providers.catalog",
                heartbeat_message=f"[{provider_id}] catalog fetch running...",
                work=lambda output: fetch_provider_catalog(provider_id, project_root=project_root, on_progress=output),
            )
        except Exception as exc:  # noqa: BLE001
            return {"provider_id": provider_id, "ok": False, "error": str(exc)}

    @mcp.tool(description=_tool_description("refresh_all_catalogs", "Fetch and persist model catalogs for all providers that support it."))
    async def refresh_all_catalogs(ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.catalog import (
            refresh_all_catalogs as _refresh,
        )
        project_root = _project_root()
        return await run_blocking_with_output(
            ctx=ctx,
            logger="providers.catalog",
            heartbeat_message="Fetching provider catalogs...",
            work=lambda output: _refresh(project_root=project_root, on_progress=output),
        )

   # --- lifecycle tools (write) ---

    @mcp.tool(description=_tool_description("install_provider", "Install a provider CLI, with dry-run support."))
    async def install_provider(provider_id: str, dry_run: bool = False, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.lifecycle import (
            install_provider_cli,
        )
        project_root = _project_root()
        return await run_blocking_with_output(
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

    @mcp.tool(description=_tool_description("uninstall_provider", "Uninstall a provider CLI, with dry-run support."))
    async def uninstall_provider(provider_id: str, dry_run: bool = False, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.lifecycle import (
            uninstall_provider_cli,
        )
        project_root = _project_root()
        return await run_blocking_with_output(
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

    @mcp.tool(description=_tool_description("repair_provider", "Repair a provider CLI by installing it if missing."))
    async def repair_provider(provider_id: str, dry_run: bool = False, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.lifecycle import repair_provider_cli
        project_root = _project_root()
        return await run_blocking_with_output(
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

    @mcp.tool(description=_tool_description("set_provider_enabled", "Enable or disable a provider in providers.yaml."))
    def set_provider_enabled(provider_id: str, enabled: bool) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.provider_config import (
            set_provider_enabled as _set_enabled,
        )
        project_root = _project_root()
        _set_enabled(project_root, provider_id, enabled=enabled)
        return {"provider_id": provider_id, "enabled": enabled, "ok": True}

    @mcp.tool(description=_tool_description("apply_provider_surfaces", "Apply managed provider surface blocks to agent files."))
    async def apply_provider_surfaces(provider_id: str | None = None, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.surfaces.manager import (
            apply_provider_surfaces as _apply,
        )
        project_root = _project_root()
        return await run_blocking_with_output(
            ctx=ctx,
            logger="providers.surfaces",
            heartbeat_message="Applying provider surfaces...",
            work=lambda output: _apply(project_root, provider_id=provider_id, on_progress=output),
        )

    @mcp.tool(description=_tool_description("prune_provider_surfaces", "Remove stale managed provider surface blocks from agent files."))
    async def prune_provider_surfaces(provider_id: str | None = None, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.surfaces.manager import (
            prune_provider_surfaces as _prune,
        )
        project_root = _project_root()
        return await run_blocking_with_output(
            ctx=ctx,
            logger="providers.surfaces",
            heartbeat_message="Pruning provider surfaces...",
            work=lambda output: _prune(project_root, provider_id=provider_id, on_progress=output),
        )

    @mcp.tool(description=_tool_description("reconcile_provider", "Reconcile a single provider against host state and sync config or surfaces."))
    async def reconcile_provider(provider_id: str, fetch_catalog: bool = False, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.lifecycle import (
            reconcile_provider as _reconcile,
        )
        project_root = _project_root()
        return await run_blocking_with_output(
            ctx=ctx,
            logger="providers.reconcile",
            heartbeat_message=f"[{provider_id}] reconcile still running...",
            work=lambda output: _reconcile(provider_id, project_root=project_root, fetch_catalog=fetch_catalog, on_progress=output),
        )

    @mcp.tool(description=_tool_description("reconcile_all_providers", "Reconcile all registered providers against host state."))
    async def reconcile_all_providers(fetch_catalogs: bool = False, ctx: Context = None) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.lifecycle import (
            reconcile_all_providers as _reconcile_all,
        )
        project_root = _project_root()
        return await run_blocking_with_output(
            ctx=ctx,
            logger="providers.reconcile",
            heartbeat_message="Reconciling providers...",
            work=lambda output: _reconcile_all(project_root=project_root, fetch_catalogs=fetch_catalogs, on_progress=output),
        )

    # --- MCP config management tools ---

    @mcp.tool(description=_tool_description("list_provider_mcp_servers", "List current MCP server entries in a provider's config file."))
    def list_provider_mcp_servers(provider_id: str) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.mcp import (
            list_provider_mcp_servers as _list_mcp,
        )
        return _list_mcp(provider_id, _project_root())

    @mcp.tool(description=_tool_description("add_mcp_server_to_provider", "Add or update a named MCP server entry in a provider's config file."))
    def add_mcp_server_to_provider(
        provider_id: str,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.mcp import (
            add_provider_mcp_server as _add_mcp,
        )
        return _add_mcp(
            provider_id, name, command, _project_root(),
            args=tuple(args or []),
            env=env,
        )

    @mcp.tool(description=_tool_description("remove_provider_mcp_server", "Remove a named MCP server entry from a provider's config file."))
    def remove_provider_mcp_server(provider_id: str, server_name: str) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.mcp import (
            remove_provider_mcp_server as _remove_mcp,
        )
        return _remove_mcp(provider_id, server_name, _project_root())

    @mcp.tool(description=_tool_description("reload_provider_mcp", "Signal or reload a provider after its MCP config has changed."))
    def reload_provider_mcp(provider_id: str) -> dict[str, Any]:
        from audiagentic.components.optional.providers.services.mcp import (
            reload_provider_mcp as _reload_mcp,
        )
        return _reload_mcp(provider_id, _project_root())

    return mcp


def main() -> int:
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
