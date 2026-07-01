"""Planning component management MCP server — status and implementation selection."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.features.lifecycle import enable_implementation
from audiagentic.foundation.features.registry import get_implementations
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

logger = logging.getLogger(__name__)

mcp = mcp_server(__name__)

_COMPONENT_ID = "agent-planning"


def _active_implementation(project_root: Path) -> str:
    """Return the enabled implementation ID, or the first registered default."""
    from audiagentic.components.planning.planning_api import active_implementation_id
    return active_implementation_id(project_root)


@mcp.tool()
@log_tool_call
def planning_status() -> dict[str, Any]:
    from audiagentic.components.planning.planning_api import planning_status as _status
    return _status(project_root_from_env())


@mcp.tool()
@log_tool_call
def planning_list_implementations() -> dict[str, Any]:
    root = project_root_from_env()
    impls = get_implementations(_COMPONENT_ID)
    return {
        "active": _active_implementation(root),
        "implementations": {
            impl_id: {
                "display_name": desc.display_name,
                "description": desc.description,
            }
            for impl_id, desc in impls.items()
        },
    }


@mcp.tool()
@log_tool_call
def planning_select_implementation(implementation: str) -> dict[str, Any]:
    root = project_root_from_env()
    return enable_implementation(root, _COMPONENT_ID, implementation)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("planning-manage")
    mcp.run()


if __name__ == "__main__":
    main()
