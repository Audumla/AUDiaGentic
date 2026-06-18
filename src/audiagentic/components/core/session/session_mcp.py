"""AUDiaGentic session MCP server."""

from __future__ import annotations

import argparse
import logging
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
    run_blocking_with_output,
)

from . import session_api

register_all_components()

logger = logging.getLogger(__name__)


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_SESSION, "ag-session-mgmt")


def _server_instructions() -> str:
    decl = _server_decl()
    return decl.instructions if decl else ""


def _tool_description(name: str) -> str:
    decl = _server_decl()
    return decl.tool_descriptions.get(name, "") if decl else ""


def _report_error(tool_name: str, exc: Exception) -> dict[str, Any]:
    logger.exception("session tool failed: %s", tool_name)
    return {"ok": False, "error": str(exc), "tool": tool_name}


def build_server() -> FastMCP:
    mcp = FastMCP(
        "ag-session-mgmt",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("status"))
    @log_tool_call
    def status() -> dict[str, Any]:
        try:
            return session_api.status(project_root_from_env())
        except Exception as exc:
            return _report_error("status", exc)

    @mcp.tool(description=_tool_description("config"))
    @log_tool_call
    def config() -> dict[str, Any]:
        try:
            return session_api.config()
        except Exception as exc:
            return _report_error("config", exc)

    @mcp.tool(description=_tool_description("set_auto_update"))
    @log_tool_call
    def set_auto_update(enabled: bool) -> dict[str, Any]:
        try:
            return session_api.set_auto_update(enabled)
        except Exception as exc:
            return _report_error("set_auto_update", exc)

    @mcp.tool(description=_tool_description("cli_visibility"))
    @log_tool_call
    def cli_visibility() -> dict[str, Any]:
        try:
            return session_api.cli_visibility(project_root_from_env())
        except Exception as exc:
            return _report_error("cli_visibility", exc)

    @mcp.tool(description=_tool_description("set_cli_visibility"))
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
            return _report_error("set_cli_visibility", exc)

    @mcp.tool(description=_tool_description("refresh_harness_config"))
    @log_tool_call
    def refresh_harness_config() -> dict[str, Any]:
        try:
            return session_api.refresh_harness_config(project_root_from_env())
        except Exception as exc:
            return _report_error("refresh_harness_config", exc)

    @mcp.tool(description=_tool_description("update_embedded_rig"))
    @log_tool_call
    async def update_embedded_rig(ctx: Context) -> dict[str, Any]:
        try:
            return await session_api.update_embedded_rig(
                ctx=ctx,
                run_with_output=run_blocking_with_output,
            )
        except Exception as exc:
            return _report_error("update_embedded_rig", exc)

    @mcp.tool(description=_tool_description("update_global_embedded_rig"))
    @log_tool_call
    async def update_global_embedded_rig(ctx: Context) -> dict[str, Any]:
        try:
            return await session_api.update_global_embedded_rig(
                ctx=ctx,
                run_with_output=run_blocking_with_output,
            )
        except Exception as exc:
            return _report_error("update_global_embedded_rig", exc)

    return mcp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readonly", action="store_true", help="Read-only mode (no-op, server is always read-only)")
    parser.add_argument("--smoke-only", action="store_true", help="Smoking mode (no-op)")
    parser.parse_args()

    from audiagentic.foundation.logging import bootstrap
    bootstrap("session")
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
