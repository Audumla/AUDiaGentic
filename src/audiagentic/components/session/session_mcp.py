"""AUDiaGentic session MCP server."""

from __future__ import annotations

import argparse
import os
from typing import Any

from audiagentic.foundation.components.ids import COMPONENT_SESSION
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    server_instructions,
    tool_boundary,
)

from . import session_api


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_SESSION, "ag-session-mgmt")


def build_server() -> FastMCP:
    decl = _server_decl()
    mcp = mcp_server(__name__, instructions=server_instructions(decl))

    @mcp.tool()
    @tool_boundary
    def status() -> dict[str, Any]:
        return session_api.status(project_root_from_env())

    @mcp.tool()
    @tool_boundary
    def config() -> dict[str, Any]:
        return session_api.config()

    @mcp.tool()
    @tool_boundary
    def set_auto_update(enabled: bool) -> dict[str, Any]:
        return session_api.set_auto_update(enabled)

    @mcp.tool()
    @tool_boundary
    def refresh_harness_config() -> dict[str, Any]:
        return session_api.refresh_harness_config(project_root_from_env())

    @mcp.tool()
    @tool_boundary
    async def update_rig(scope: str = "local") -> dict[str, Any]:
        return await session_api.update_rig(scope=scope)

    @mcp.tool()
    @tool_boundary
    def rig_upgrade_status(scope: str = "local") -> dict[str, Any]:
        return session_api.rig_upgrade_status(scope=scope)

    return mcp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--readonly", action="store_true", help="Read-only mode (no-op, server is always read-only)"
    )
    parser.add_argument(
        "--smoke-only", action="store_true", help="Smoke mode for fast MCP health checks"
    )
    args = parser.parse_args()
    if args.smoke_only:
        os.environ["AUDIAGENTIC_MCP_SMOKE_ONLY"] = "1"

    from audiagentic.runtime.harness import wire_harness_status
    wire_harness_status()

    run_mcp_server(build_server(), "session")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
