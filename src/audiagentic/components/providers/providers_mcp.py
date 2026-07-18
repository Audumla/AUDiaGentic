"""AUDiaGentic providers component MCP server."""
from __future__ import annotations

from typing import Any

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.contracts.lifecycle_modes import (
    normalize_provider_cli_mode,
)
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
    async def manage_cli_lifecycle(provider_id: str, mode: str) -> dict[str, Any]:
        result = await providers_api.manage_cli_lifecycle(
            project_root_from_env(), provider_id, mode=normalize_provider_cli_mode(mode)
        )
        return result.to_mapping()

    @mcp.tool()
    @log_tool_call
    def operate_provider_surface(
        provider_id: str,
        mode: str,
        contribution_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from audiagentic.components.providers.contracts.generated_surface import (
            GeneratedSurfaceRequest,
        )

        if contribution_ids is None or len(contribution_ids) == 0:
            result = providers_api.operate_provider_surfaces(
                project_root_from_env(),
                provider_id=provider_id,
                mode=mode,
            )
            return result.to_mapping()

        request = GeneratedSurfaceRequest(
            ownership_scope=provider_id,
            contribution_ids=tuple(contribution_ids),
        )
        result = providers_api.operate_provider_surface(
            project_root_from_env(),
            provider_id,
            mode=mode,
            request=request,
        )
        return result.to_mapping()

    @mcp.tool()
    @log_tool_call
    def operate_provider_surfaces(
        mode: str,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        """Operate on generated surfaces for one or all active providers."""
        from audiagentic.components.providers.contracts.generated_surface import (
            GeneratedSurfaceResult,
        )

        results = providers_api.operate_provider_surfaces(
            project_root_from_env(),
            provider_id=provider_id,
            mode=mode,
        )
        if isinstance(results, GeneratedSurfaceResult):
            return results.to_mapping()
        return {
            "results": [r.to_mapping() if hasattr(r, "to_mapping") else r for r in results],
        }

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
    def list_model_inventory() -> dict[str, Any]:
        return providers_api.list_model_inventory(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def refresh_model_source_catalog(source_id: str) -> dict[str, Any]:
        return providers_api.refresh_model_source_catalog(
            project_root_from_env(), source_id
        )

    @mcp.tool()
    @log_tool_call
    def model_vendor_set_enabled(vendor_id: str, enabled: bool) -> dict[str, Any]:
        return providers_api.model_vendor_set_enabled(
            project_root_from_env(), vendor_id, enabled
        )

    @mcp.tool()
    @log_tool_call
    def apply_model_sources() -> dict[str, Any]:
        return providers_api.apply_model_sources(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def model_source_add(source_id: str, config: dict[str, Any]) -> dict[str, Any]:
        return providers_api.model_source_add(project_root_from_env(), source_id, config)

    @mcp.tool()
    @log_tool_call
    def model_source_update(source_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        return providers_api.model_source_update(project_root_from_env(), source_id, updates)

    @mcp.tool()
    @log_tool_call
    def model_source_remove(source_id: str) -> dict[str, Any]:
        return providers_api.model_source_remove(project_root_from_env(), source_id)

    @mcp.tool()
    @log_tool_call
    def model_source_set_enabled(source_id: str, enabled: bool) -> dict[str, Any]:
        return providers_api.model_source_set_enabled(
            project_root_from_env(), source_id, enabled
        )

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

