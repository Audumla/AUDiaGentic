"""AUDiaGentic planning component MCP server.

Exposes planning status and item counts to the Pi TUI.
Reads AUDIAGENTIC_REPO_ROOT from env to locate the target project.
"""

from __future__ import annotations

import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components.ids import COMPONENT_PLANNING
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.foundation.mcp.component_server import log_tool_call, project_root_from_env

from .planning_api import (
    planning_events as _planning_events,
)
from .planning_api import (
    planning_index as _planning_index,
)
from .planning_api import (
    planning_status as _planning_status,
)
from .planning_api import (
    planning_summary as _planning_summary,
)

register_all_components()

def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PLANNING, "ag-planning-mgmt")


def _server_instructions() -> str:
    decl = _server_decl()
    return decl.instructions if decl else ""


def _tool_description(name: str) -> str:
    decl = _server_decl()
    return decl.tool_descriptions.get(name, "") if decl else ""


def build_server() -> FastMCP:
    mcp = FastMCP(
        "ag-planning-mgmt",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("planning_status"))
    @log_tool_call
    def planning_status() -> dict[str, Any]:
        return _planning_status(project_root_from_env())

    @mcp.tool(description=_tool_description("planning_summary"))
    @log_tool_call
    def planning_summary() -> dict[str, Any]:
        return _planning_summary(project_root_from_env())

    @mcp.tool(description=_tool_description("planning_index"))
    @log_tool_call
    def planning_index(index_name: str) -> dict[str, Any]:
        return _planning_index(project_root_from_env(), index_name)

    @mcp.tool(description=_tool_description("planning_events"))
    @log_tool_call
    def planning_events(limit: int = 20) -> dict[str, Any]:
        return _planning_events(project_root_from_env(), limit=limit)

    return mcp


def main() -> int:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("planning")
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

