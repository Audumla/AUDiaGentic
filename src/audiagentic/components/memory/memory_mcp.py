"""Memory component management MCP server."""
from __future__ import annotations

from typing import Any

from audiagentic.components.memory import memory_api
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

register_all_components()


def build_server() -> FastMCP:
    mcp = mcp_server(__name__)

    @mcp.tool()
    @log_tool_call
    def memory_status() -> dict[str, Any]:
        return memory_api.memory_status(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def memory_list_implementations() -> dict[str, Any]:
        return memory_api.memory_list_implementations(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def memory_select_implementation(implementation_id: str) -> dict[str, Any]:
        return memory_api.memory_select_implementation(
            project_root_from_env(), implementation_id
        )

    @mcp.tool()
    @log_tool_call
    def memory_get_config(implementation_id: str | None = None) -> dict[str, Any]:
        return memory_api.memory_get_config(project_root_from_env(), implementation_id)

    @mcp.tool()
    @log_tool_call
    def memory_set_config(
        implementation_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        return memory_api.memory_set_config(
            project_root_from_env(), implementation_id, updates
        )

    return mcp


def main() -> int:
    run_mcp_server(build_server(), "memory-mgmt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
