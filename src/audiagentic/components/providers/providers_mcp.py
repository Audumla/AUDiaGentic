"""AUDiaGentic providers component MCP server."""
from __future__ import annotations

from typing import Any

from audiagentic.components.providers import providers_api
from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    server_instructions,
    tool_description,
)

register_all_components()


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PROVIDERS, "ag-providers-mgmt")


def build_server() -> FastMCP:
    decl = _server_decl()
    mcp = mcp_server(__name__, instructions=server_instructions(decl))

    @mcp.tool(description=tool_description(decl, "list_providers"))
    @log_tool_call
    def list_providers() -> dict[str, Any]:
        return providers_api.list_providers(project_root_from_env())

    @mcp.tool(description=tool_description(decl, "get_provider_status"))
    @log_tool_call
    def get_provider_status(provider_id: str) -> dict[str, Any]:
        return providers_api.get_provider_status(project_root_from_env(), provider_id)

    @mcp.tool(description=tool_description(decl, "list_provider_descriptors"))
    @log_tool_call
    def list_provider_descriptors() -> list[dict[str, Any]]:
        return providers_api.list_provider_descriptors()

    @mcp.tool(description=tool_description(decl, "list_provider_models"))
    @log_tool_call
    def list_provider_models(provider_id: str) -> dict[str, Any]:
        return providers_api.list_provider_models(project_root_from_env(), provider_id)

    @mcp.tool(description=tool_description(decl, "refresh_provider_catalog"))
    @log_tool_call
    async def refresh_provider_catalog(provider_id: str) -> dict[str, Any]:
        return await providers_api.refresh_provider_catalog(
            project_root_from_env(), provider_id
        )

    @mcp.tool(description=tool_description(decl, "refresh_all_catalogs"))
    @log_tool_call
    async def refresh_all_catalogs() -> dict[str, Any]:
        return await providers_api.refresh_all_catalogs(project_root_from_env())

    @mcp.tool(description=tool_description(decl, "install_provider"))
    @log_tool_call
    async def install_provider(provider_id: str, dry_run: bool = False) -> dict[str, Any]:
        return await providers_api.install_provider(
            project_root_from_env(), provider_id, dry_run=dry_run
        )

    @mcp.tool(description=tool_description(decl, "uninstall_provider"))
    @log_tool_call
    async def uninstall_provider(provider_id: str, dry_run: bool = False) -> dict[str, Any]:
        return await providers_api.uninstall_provider(
            project_root_from_env(), provider_id, dry_run=dry_run
        )

    @mcp.tool(description=tool_description(decl, "repair_provider"))
    @log_tool_call
    async def repair_provider(provider_id: str, dry_run: bool = False) -> dict[str, Any]:
        return await providers_api.repair_provider(
            project_root_from_env(), provider_id, dry_run=dry_run
        )

    @mcp.tool(description=tool_description(decl, "apply_provider_surfaces"))
    @log_tool_call
    async def apply_provider_surfaces(provider_id: str | None = None) -> dict[str, Any]:
        return await providers_api.apply_provider_surfaces(
            project_root_from_env(), provider_id=provider_id
        )

    @mcp.tool(description=tool_description(decl, "prune_provider_surfaces"))
    @log_tool_call
    async def prune_provider_surfaces(provider_id: str | None = None) -> dict[str, Any]:
        return await providers_api.prune_provider_surfaces(
            project_root_from_env(), provider_id=provider_id
        )

    @mcp.tool(description=tool_description(decl, "reconcile_provider"))
    @log_tool_call
    async def reconcile_provider(provider_id: str, fetch_catalog: bool = False) -> dict[str, Any]:
        return await providers_api.reconcile_provider(
            project_root_from_env(), provider_id, fetch_catalog=fetch_catalog
        )

    @mcp.tool(description=tool_description(decl, "reconcile_all_providers"))
    @log_tool_call
    async def reconcile_all_providers(fetch_catalogs: bool = False) -> dict[str, Any]:
        return await providers_api.reconcile_all_providers(
            project_root_from_env(), fetch_catalogs=fetch_catalogs
        )

    return mcp


def main() -> int:
    run_mcp_server(build_server(), "providers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
