"""AUDiaGentic project component MCP server."""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.components.ids import COMPONENT_PROJECT
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    server_instructions,
    tool_boundary,
)

from . import project_api


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PROJECT, "ag-project-mgmt")


def build_server() -> FastMCP:
    decl = _server_decl()
    mcp = mcp_server(__name__, instructions=server_instructions(decl))

    @mcp.tool()
    @tool_boundary
    def project_status() -> dict[str, Any]:
        return project_api.project_status(project_root_from_env())

    @mcp.tool()
    @tool_boundary
    def list_components() -> list[dict[str, Any]]:
        return project_api.list_components(project_root_from_env())

    @mcp.tool()
    @tool_boundary
    def install_component(component_id: str) -> dict[str, Any]:
        return project_api.install_component(project_root_from_env(), component_id)

    @mcp.tool()
    @tool_boundary
    def uninstall_component(component_id: str, remove_configs: bool = False) -> dict[str, Any]:
        return project_api.uninstall_component(
            project_root_from_env(),
            component_id,
            remove_configs=remove_configs,
        )

    @mcp.tool()
    @tool_boundary
    def enable_component(component_id: str) -> dict[str, Any]:
        return project_api.enable_component(project_root_from_env(), component_id)

    @mcp.tool()
    @tool_boundary
    def disable_component(component_id: str) -> dict[str, Any]:
        return project_api.disable_component(project_root_from_env(), component_id)

    @mcp.tool()
    @tool_boundary
    def read_project_file(relative_path: str) -> dict[str, Any]:
        return project_api.read_project_file(project_root_from_env(), relative_path)

    @mcp.tool()
    @tool_boundary
    def list_project_instructions() -> list[dict[str, Any]]:
        return project_api.list_project_instructions(project_root_from_env())

    @mcp.tool()
    @tool_boundary
    def get_project_instruction(item_id: str) -> dict[str, Any]:
        return project_api.get_project_instruction(project_root_from_env(), item_id)

    @mcp.tool()
    @tool_boundary
    def create_project_instruction(item_id: str, title: str, body: str, preferred_targets: list[str] | None = None) -> dict[str, Any]:
        return project_api.create_project_instruction(project_root_from_env(), item_id, title, body, preferred_targets)

    @mcp.tool()
    @tool_boundary
    def update_project_instruction(item_id: str, title: str | None = None, body: str | None = None, preferred_targets: list[str] | None = None) -> dict[str, Any]:
        return project_api.update_project_instruction(project_root_from_env(), item_id, title, body, preferred_targets)

    @mcp.tool()
    @tool_boundary
    def delete_project_instruction(item_id: str) -> dict[str, Any]:
        return project_api.delete_project_instruction(project_root_from_env(), item_id)

    @mcp.tool()
    @tool_boundary
    def list_project_skills() -> list[dict[str, Any]]:
        return project_api.list_project_skills(project_root_from_env())

    @mcp.tool()
    @tool_boundary
    def get_project_skill(item_id: str) -> dict[str, Any]:
        return project_api.get_project_skill(project_root_from_env(), item_id)

    @mcp.tool()
    @tool_boundary
    def create_project_skill(item_id: str, content: str) -> dict[str, Any]:
        return project_api.create_project_skill(project_root_from_env(), item_id, content)

    @mcp.tool()
    @tool_boundary
    def update_project_skill(item_id: str, content: str) -> dict[str, Any]:
        return project_api.update_project_skill(project_root_from_env(), item_id, content)

    @mcp.tool()
    @tool_boundary
    def delete_project_skill(item_id: str) -> dict[str, Any]:
        return project_api.delete_project_skill(project_root_from_env(), item_id)

    @mcp.tool()
    @tool_boundary
    def runtime_sync_contract() -> dict[str, Any]:
        return project_api.runtime_sync_contract()

    @mcp.tool()
    @tool_boundary
    def get_option_provenance(component_id: str | None = None) -> dict[str, Any]:
        return project_api.get_option_provenance(project_root_from_env(), component_id)

    return mcp


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", default=None)
    args, _ = parser.parse_known_args()
    if args.project_root:
        import os

        os.environ["AUDIAGENTIC_REPO_ROOT"] = args.project_root

    from audiagentic.runtime.harness import wire_harness_status
    wire_harness_status()

    run_mcp_server(build_server(), "project")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
