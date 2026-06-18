"""AUDiaGentic session MCP server."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import Context
except ImportError:  # pragma: no cover - exercised by missing optional dep only
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components.ids import COMPONENT_SESSION
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    project_root_from_env,
    report_error,
    run_blocking_with_output,
    server_instructions,
    tool_description,
)

from . import session_api

register_all_components()

logger = logging.getLogger(__name__)


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_SESSION, "ag-session-mgmt")


def build_server() -> FastMCP:
    decl = _server_decl()
    mcp = FastMCP(
        "ag-session-mgmt",
        instructions=server_instructions(decl),
    )

    @mcp.tool(description=tool_description(decl, "status"))
    @log_tool_call
    def status() -> dict[str, Any]:
        try:
            return session_api.status(project_root_from_env())
        except Exception as exc:
            return report_error("session", "status", exc, logger)

    @mcp.tool(description=tool_description(decl, "config"))
    @log_tool_call
    def config() -> dict[str, Any]:
        try:
            return session_api.config()
        except Exception as exc:
            return report_error("session", "config", exc, logger)

    @mcp.tool(description=tool_description(decl, "set_auto_update"))
    @log_tool_call
    def set_auto_update(enabled: bool) -> dict[str, Any]:
        try:
            return session_api.set_auto_update(enabled)
        except Exception as exc:
            return report_error("session", "set_auto_update", exc, logger)

    @mcp.tool(description=tool_description(decl, "cli_visibility"))
    @log_tool_call
    def cli_visibility() -> dict[str, Any]:
        try:
            return session_api.cli_visibility(project_root_from_env())
        except Exception as exc:
            return report_error("session", "cli_visibility", exc, logger)

    @mcp.tool(description=tool_description(decl, "set_cli_visibility"))
    @log_tool_call
    def set_cli_visibility(
        show_thinking_blocks: bool | None = None,
        show_tool_blocks: bool | None = None,
        scope: str = "project",
    ) -> dict[str, Any]:
        try:
            return session_api.set_cli_visibility(
                project_root_from_env(),
                show_thinking_blocks=show_thinking_blocks,
                show_tool_blocks=show_tool_blocks,
                scope=scope,
            )
        except Exception as exc:
            return report_error("session", "set_cli_visibility", exc, logger)

    @mcp.tool(description=tool_description(decl, "refresh_harness_config"))
    @log_tool_call
    def refresh_harness_config() -> dict[str, Any]:
        try:
            return session_api.refresh_harness_config(project_root_from_env())
        except Exception as exc:
            return report_error("session", "refresh_harness_config", exc, logger)

    @mcp.tool(description=tool_description(decl, "update_rig"))
    @log_tool_call
    async def update_rig(ctx: Context, scope: str = "local") -> dict[str, Any]:
        try:
            return await session_api.update_rig(
                ctx=ctx,
                run_with_output=run_blocking_with_output,
                scope=scope,
            )
        except Exception as exc:
            return report_error("session", "update_rig", exc, logger)

    return mcp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readonly", action="store_true", help="Read-only mode (no-op, server is always read-only)")
    parser.add_argument("--smoke-only", action="store_true", help="Smoke mode for fast MCP health checks")
    args = parser.parse_args()
    if args.smoke_only:
        os.environ["AUDIAGENTIC_MCP_SMOKE_ONLY"] = "1"

    from audiagentic.foundation.logging import bootstrap
    bootstrap("session")
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
