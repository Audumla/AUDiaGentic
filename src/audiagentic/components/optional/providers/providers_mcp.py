"""AUDiaGentic providers component MCP server."""
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

from audiagentic.components.optional.providers import providers_api
from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import log_tool_call, run_blocking_with_output

register_all_components()


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if not repo_root:
        raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")
    return Path(repo_root)


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PROVIDERS, "ag-providers-mgmt")


def _server_instructions() -> str:
    decl = _server_decl()
    return decl.instructions if decl else ""


def _tool_description(name: str) -> str:
    decl = _server_decl()
    return decl.tool_descriptions.get(name, "") if decl else ""


def build_server() -> FastMCP:
    mcp = FastMCP(
        "ag-providers-mgmt",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("list_providers"))
    @log_tool_call
    def list_providers() -> dict[str, Any]:
        return providers_api.list_providers(_project_root())

    @mcp.tool(description=_tool_description("get_provider_status"))
    @log_tool_call
    def get_provider_status(provider_id: str) -> dict[str, Any]:
        return providers_api.get_provider_status(_project_root(), provider_id)

    @mcp.tool(description=_tool_description("list_provider_descriptors"))
    @log_tool_call
    def list_provider_descriptors() -> list[dict[str, Any]]:
        return providers_api.list_provider_descriptors()

    @mcp.tool(description=_tool_description("list_provider_models"))
    @log_tool_call
    def list_provider_models(provider_id: str) -> dict[str, Any]:
        return providers_api.list_provider_models(_project_root(), provider_id)

    @mcp.tool(description=_tool_description("refresh_provider_catalog"))
    @log_tool_call
    async def refresh_provider_catalog(provider_id: str, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.refresh_provider_catalog(
            _project_root(),
            provider_id,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("refresh_all_catalogs"))
    @log_tool_call
    async def refresh_all_catalogs(ctx: Context = None) -> dict[str, Any]:
        return await providers_api.refresh_all_catalogs(
            _project_root(),
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("install_provider"))
    @log_tool_call
    async def install_provider(provider_id: str, dry_run: bool = False, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.install_provider(
            _project_root(),
            provider_id,
            dry_run=dry_run,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("uninstall_provider"))
    @log_tool_call
    async def uninstall_provider(provider_id: str, dry_run: bool = False, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.uninstall_provider(
            _project_root(),
            provider_id,
            dry_run=dry_run,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("repair_provider"))
    @log_tool_call
    async def repair_provider(provider_id: str, dry_run: bool = False, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.repair_provider(
            _project_root(),
            provider_id,
            dry_run=dry_run,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("apply_provider_surfaces"))
    @log_tool_call
    async def apply_provider_surfaces(provider_id: str | None = None, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.apply_provider_surfaces(
            _project_root(),
            provider_id=provider_id,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("prune_provider_surfaces"))
    @log_tool_call
    async def prune_provider_surfaces(provider_id: str | None = None, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.prune_provider_surfaces(
            _project_root(),
            provider_id=provider_id,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("reconcile_provider"))
    @log_tool_call
    async def reconcile_provider(provider_id: str, fetch_catalog: bool = False, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.reconcile_provider(
            _project_root(),
            provider_id,
            fetch_catalog=fetch_catalog,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    @mcp.tool(description=_tool_description("reconcile_all_providers"))
    @log_tool_call
    async def reconcile_all_providers(fetch_catalogs: bool = False, ctx: Context = None) -> dict[str, Any]:
        return await providers_api.reconcile_all_providers(
            _project_root(),
            fetch_catalogs=fetch_catalogs,
            ctx=ctx,
            run_with_output=run_blocking_with_output,
        )

    return mcp


def main() -> int:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("providers")
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
