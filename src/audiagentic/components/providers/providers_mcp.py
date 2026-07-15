"""AUDiaGentic providers component MCP server."""
from __future__ import annotations

from typing import Any

from audiagentic.components.providers import providers_api
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    server_instructions,
)

_COMPONENT_ID = "providers"


def _server_decl():
    return get_mcp_server_declaration(_COMPONENT_ID, "ag-providers-mgmt")


def build_server() -> FastMCP:
    decl = _server_decl()
    mcp = mcp_server(__name__, instructions=server_instructions(decl))

    @mcp.tool()
    @log_tool_call
    def list_providers() -> dict[str, Any]:
        return providers_api.list_providers(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def get_provider_status(provider_id: str) -> dict[str, Any]:
        return providers_api.get_provider_status(project_root_from_env(), provider_id)

    @mcp.tool()
    @log_tool_call
    def list_provider_descriptors() -> list[dict[str, Any]]:
        return providers_api.list_provider_descriptors()

    @mcp.tool()
    @log_tool_call
    def list_provider_models(provider_id: str) -> dict[str, Any]:
        return providers_api.list_provider_models(project_root_from_env(), provider_id)

    @mcp.tool()
    @log_tool_call
    async def refresh_provider_catalog(provider_id: str) -> dict[str, Any]:
        return await providers_api.refresh_provider_catalog(
            project_root_from_env(), provider_id
        )

    @mcp.tool()
    @log_tool_call
    async def refresh_all_catalogs() -> dict[str, Any]:
        return await providers_api.refresh_all_catalogs(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    async def install_provider(provider_id: str, dry_run: bool = False) -> dict[str, Any]:
        return await providers_api.install_provider(
            project_root_from_env(), provider_id, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    async def uninstall_provider(provider_id: str, dry_run: bool = False) -> dict[str, Any]:
        return await providers_api.uninstall_provider(
            project_root_from_env(), provider_id, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    async def repair_provider(provider_id: str, dry_run: bool = False) -> dict[str, Any]:
        return await providers_api.repair_provider(
            project_root_from_env(), provider_id, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    async def apply_provider_surfaces(provider_id: str | None = None) -> dict[str, Any]:
        return await providers_api.apply_provider_surfaces(
            project_root_from_env(), provider_id=provider_id
        )

    @mcp.tool()
    @log_tool_call
    async def prune_provider_surfaces(provider_id: str | None = None) -> dict[str, Any]:
        return await providers_api.prune_provider_surfaces(
            project_root_from_env(), provider_id=provider_id
        )

    @mcp.tool()
    @log_tool_call
    async def reconcile_provider(provider_id: str, fetch_catalog: bool = False) -> dict[str, Any]:
        return await providers_api.reconcile_provider(
            project_root_from_env(), provider_id, fetch_catalog=fetch_catalog
        )

    @mcp.tool()
    @log_tool_call
    async def reconcile_all_providers(fetch_catalogs: bool = False) -> dict[str, Any]:
        return await providers_api.reconcile_all_providers(
            project_root_from_env(), fetch_catalogs=fetch_catalogs
        )

    @mcp.tool()
    @log_tool_call
    def model_source_list() -> dict[str, Any]:
        return providers_api.model_source_list(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def model_source_add(
        source_id: str, config: dict[str, Any], apply: bool = True, dry_run: bool = False
    ) -> dict[str, Any]:
        return providers_api.model_source_add(
            project_root_from_env(), source_id, config, apply=apply, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    def model_source_update(
        source_id: str, updates: dict[str, Any], apply: bool = True, dry_run: bool = False
    ) -> dict[str, Any]:
        return providers_api.model_source_update(
            project_root_from_env(), source_id, updates, apply=apply, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    def model_source_remove(
        source_id: str, apply: bool = True, dry_run: bool = False
    ) -> dict[str, Any]:
        return providers_api.model_source_remove(
            project_root_from_env(), source_id, apply=apply, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    def model_source_set_enabled(
        source_id: str, enabled: bool, apply: bool = True, dry_run: bool = False
    ) -> dict[str, Any]:
        return providers_api.model_source_set_enabled(
            project_root_from_env(), source_id, enabled, apply=apply, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    def list_provider_models_config(provider_id: str) -> dict[str, Any]:
        return providers_api.list_provider_models_config(project_root_from_env(), provider_id)

    @mcp.tool()
    @log_tool_call
    def sync_provider_models(provider_id: str, dry_run: bool = False) -> dict[str, Any]:
        return providers_api.sync_provider_models(
            project_root_from_env(), provider_id, dry_run=dry_run
        )

    @mcp.tool()
    @log_tool_call
    def reload_provider_models(provider_id: str) -> dict[str, Any]:
        return providers_api.reload_provider_models(project_root_from_env(), provider_id)

    @mcp.tool()
    @log_tool_call
    def describe_provider(provider_id: str) -> dict[str, Any]:
        return providers_api.describe_provider(project_root_from_env(), provider_id)

    return mcp


def main() -> int:
    run_mcp_server(build_server(), "providers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

