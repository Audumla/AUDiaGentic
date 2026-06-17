"""AUDiaGentic project component MCP server."""
from __future__ import annotations

import logging
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components.ids import COMPONENT_PROJECT
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import log_tool_call, project_root_from_env

from . import project_api

register_all_components()

logger = logging.getLogger(__name__)


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PROJECT, "ag-project-mgmt")


def _server_instructions() -> str:
    decl = _server_decl()
    return decl.instructions if decl else ""


def _tool_description(name: str) -> str:
    decl = _server_decl()
    return decl.tool_descriptions.get(name, "") if decl else ""


def _report_error(tool_name: str, exc: Exception) -> dict[str, Any]:
    logger.exception("project tool failed: %s", tool_name)
    return {"ok": False, "error": str(exc), "tool": tool_name}


def build_server() -> FastMCP:
    mcp = FastMCP(
        "ag-project-mgmt",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("project_status"))
    @log_tool_call
    def project_status() -> dict[str, Any]:
        try:
            return project_api.project_status(project_root_from_env())
        except Exception as exc:
            return _report_error("project_status", exc)

    @mcp.tool(description=_tool_description("list_components"))
    @log_tool_call
    def list_components() -> list[dict[str, Any]] | dict[str, Any]:
        try:
            return project_api.list_components(project_root_from_env())
        except Exception as exc:
            return _report_error("list_components", exc)

    @mcp.tool(description=_tool_description("install_component"))
    @log_tool_call
    def install_component(component_id: str) -> dict[str, Any]:
        try:
            return project_api.install_component(project_root_from_env(), component_id)
        except Exception as exc:
            return _report_error("install_component", exc)

    @mcp.tool(description=_tool_description("uninstall_component"))
    @log_tool_call
    def uninstall_component(component_id: str, remove_configs: bool = False) -> dict[str, Any]:
        try:
            return project_api.uninstall_component(
                project_root_from_env(),
                component_id,
                remove_configs=remove_configs,
            )
        except Exception as exc:
            return _report_error("uninstall_component", exc)

    @mcp.tool(description=_tool_description("enable_component"))
    @log_tool_call
    def enable_component(component_id: str) -> dict[str, Any]:
        try:
            return project_api.enable_component(project_root_from_env(), component_id)
        except Exception as exc:
            return _report_error("enable_component", exc)

    @mcp.tool(description=_tool_description("disable_component"))
    @log_tool_call
    def disable_component(component_id: str) -> dict[str, Any]:
        try:
            return project_api.disable_component(project_root_from_env(), component_id)
        except Exception as exc:
            return _report_error("disable_component", exc)

    @mcp.tool(description=_tool_description("read_project_file"))
    @log_tool_call
    def read_project_file(relative_path: str) -> dict[str, Any]:
        try:
            return project_api.read_project_file(project_root_from_env(), relative_path)
        except Exception as exc:
            return _report_error("read_project_file", exc)

    @mcp.tool(description=_tool_description("runtime_sync_contract"))
    @log_tool_call
    def runtime_sync_contract() -> dict[str, Any]:
        try:
            return project_api.runtime_sync_contract()
        except Exception as exc:
            return _report_error("runtime_sync_contract", exc)

    return mcp


def main() -> int:
    import argparse

    from audiagentic.foundation.logging import bootstrap

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", default=None)
    args, _ = parser.parse_known_args()
    if args.project_root:
        import os

        os.environ["AUDIAGENTIC_REPO_ROOT"] = args.project_root

    bootstrap("project")
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
