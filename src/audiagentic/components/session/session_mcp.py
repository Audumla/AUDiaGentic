"""AUDiaGentic session MCP server."""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from audiagentic.foundation.components.ids import COMPONENT_SESSION
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    log_tool_call,
    mcp_server,
    project_root_from_env,
    report_error,
    run_mcp_server,
    server_instructions,
)

from . import session_api

logger = logging.getLogger(__name__)


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_SESSION, "ag-session-mgmt")


def build_server() -> FastMCP:
    decl = _server_decl()
    mcp = mcp_server(__name__, instructions=server_instructions(decl))

    @mcp.tool()
    @log_tool_call
    def status() -> dict[str, Any]:
        try:
            return session_api.status(project_root_from_env())
        except Exception as exc:
            return report_error("session", "status", exc, logger)

    @mcp.tool()
    @log_tool_call
    def config() -> dict[str, Any]:
        try:
            return session_api.config()
        except Exception as exc:
            return report_error("session", "config", exc, logger)

    @mcp.tool()
    @log_tool_call
    def set_auto_update(enabled: bool) -> dict[str, Any]:
        try:
            return session_api.set_auto_update(enabled)
        except Exception as exc:
            return report_error("session", "set_auto_update", exc, logger)

    @mcp.tool()
    @log_tool_call
    def refresh_harness_config() -> dict[str, Any]:
        try:
            return session_api.refresh_harness_config(project_root_from_env())
        except Exception as exc:
            return report_error("session", "refresh_harness_config", exc, logger)

    @mcp.tool()
    @log_tool_call
    async def update_rig(scope: str = "local") -> dict[str, Any]:
        try:
            return await session_api.update_rig(scope=scope)
        except Exception as exc:
            return report_error("session", "update_rig", exc, logger)

    @mcp.tool()
    @log_tool_call
    def rig_upgrade_status(scope: str = "local") -> dict[str, Any]:
        try:
            return session_api.rig_upgrade_status(scope=scope)
        except Exception as exc:
            return report_error("session", "rig_upgrade_status", exc, logger)

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
