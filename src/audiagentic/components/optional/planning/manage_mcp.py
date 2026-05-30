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

from .api import (
    planning_events as _planning_events,
)
from .api import (
    planning_index as _planning_index,
)
from .api import (
    planning_status as _planning_status,
)
from .api import (
    planning_summary as _planning_summary,
)

register_all_components()

def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PLANNING, "audiagentic-planning-manage")


def _server_instructions() -> str:
    decl = _server_decl()
    return (
        decl.instructions
        if decl and decl.instructions
        else (
            "AUDiaGentic planning component server. "
            "Use planning_status to check whether planning is configured, "
            "planning_summary to get item counts per kind, "
            "planning_index to read a specific planning index."
        )
    )


def _tool_description(name: str, fallback: str) -> str:
    decl = _server_decl()
    if decl and name in decl.tool_descriptions:
        return decl.tool_descriptions[name]
    return fallback


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-planning-manage",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("planning_status", "Return planning component installation status for the project."))
    @log_tool_call
    def planning_status() -> dict[str, Any]:
        return _planning_status(project_root_from_env())

    @mcp.tool(description=_tool_description("planning_summary", "Return item counts per planning kind and current ID counters."))
    @log_tool_call
    def planning_summary() -> dict[str, Any]:
        return _planning_summary(project_root_from_env())

    @mcp.tool(description=_tool_description("planning_index", "Read a specific planning index."))
    @log_tool_call
    def planning_index(index_name: str) -> dict[str, Any]:
        return _planning_index(project_root_from_env(), index_name)

    @mcp.tool(description=_tool_description("planning_events", "Return recent planning events from events.jsonl."))
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
