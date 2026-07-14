"""AUDiaGentic project component MCP server."""
from __future__ import annotations

import logging
from typing import Any

from audiagentic.foundation.components.ids import COMPONENT_PROJECT
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

from . import project_api

logger = logging.getLogger(__name__)


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PROJECT, "ag-project-mgmt")


def build_server() -> FastMCP:
    decl = _server_decl()
    mcp = mcp_server(__name__, instructions=server_instructions(decl))

    @mcp.tool()
    @log_tool_call
    def project_status() -> dict[str, Any]:
        try:
            return project_api.project_status(project_root_from_env())
        except Exception as exc:
            return report_error("project", "project_status", exc, logger)

    @mcp.tool()
    @log_tool_call
    def list_components() -> list[dict[str, Any]] | dict[str, Any]:
        try:
            return project_api.list_components(project_root_from_env())
        except Exception as exc:
            return report_error("project", "list_components", exc, logger)

    @mcp.tool()
    @log_tool_call
    def install_component(component_id: str) -> dict[str, Any]:
        try:
            return project_api.install_component(project_root_from_env(), component_id)
        except Exception as exc:
            return report_error("project", "install_component", exc, logger)

    @mcp.tool()
    @log_tool_call
    def uninstall_component(component_id: str, remove_configs: bool = False) -> dict[str, Any]:
        try:
            return project_api.uninstall_component(
                project_root_from_env(),
                component_id,
                remove_configs=remove_configs,
            )
        except Exception as exc:
            return report_error("project", "uninstall_component", exc, logger)

    @mcp.tool()
    @log_tool_call
    def enable_component(component_id: str) -> dict[str, Any]:
        try:
            return project_api.enable_component(project_root_from_env(), component_id)
        except Exception as exc:
            return report_error("project", "enable_component", exc, logger)

    @mcp.tool()
    @log_tool_call
    def disable_component(component_id: str) -> dict[str, Any]:
        try:
            return project_api.disable_component(project_root_from_env(), component_id)
        except Exception as exc:
            return report_error("project", "disable_component", exc, logger)

    @mcp.tool()
    @log_tool_call
    def read_project_file(relative_path: str) -> dict[str, Any]:
        try:
            return project_api.read_project_file(project_root_from_env(), relative_path)
        except Exception as exc:
            return report_error("project", "read_project_file", exc, logger)

    @mcp.tool()
    @log_tool_call
    def runtime_sync_contract() -> dict[str, Any]:
        try:
            return project_api.runtime_sync_contract()
        except Exception as exc:
            return report_error("project", "runtime_sync_contract", exc, logger)

    @mcp.tool()
    @log_tool_call
    def get_option_provenance(component_id: str | None = None) -> dict[str, Any]:
        try:
            return project_api.get_option_provenance(project_root_from_env(), component_id)
        except Exception as exc:
            return report_error("project", "get_option_provenance", exc, logger)

    return mcp


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", default=None)
    args, _ = parser.parse_known_args()
    if args.project_root:
        import os

        os.environ["AUDIAGENTIC_REPO_ROOT"] = args.project_root

    run_mcp_server(build_server(), "project")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

