"""Planning component management MCP server — status and implementation selection."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.features.lifecycle import enable_implementation
from audiagentic.foundation.features.registry import get_implementations
from audiagentic.foundation.features.state import get_component_state
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
    component = get_component_state(project_root, _COMPONENT_ID)
    implementations = component.get("implementations") or {}
    if isinstance(implementations, dict):
        for impl_id, state in implementations.items():
            if isinstance(state, dict) and state.get("enabled"):
                return impl_id
    # Fall back to descriptor-defined default, then first sorted
    impls = get_implementations(_COMPONENT_ID)
    for impl_id in sorted(impls):
        if impls[impl_id].raw.get("default"):
            return impl_id
    return next(iter(sorted(impls)), "local-docs")


@mcp.tool()
@log_tool_call
def planning_status() -> dict[str, Any]:
    """Return planning component status: active implementation and item counts."""
    from audiagentic.components.planning.planning_api import list_items
    root = project_root_from_env()
    active_items = list_items(root, state="active")
    completed_items = list_items(root, state="completed")
    return {
        "implementation": _active_implementation(root),
        "pending_items": len(active_items),
        "completed_items": len(completed_items),
    }


@mcp.tool()
@log_tool_call
def planning_list_implementations() -> dict[str, Any]:
    """List available planning implementations and the currently active one."""
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
    """Switch the active planning implementation.

    With implementation-cardinality exclusive, enabling one disables all others.
    """
    root = project_root_from_env()
    return enable_implementation(root, _COMPONENT_ID, implementation)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("planning-manage")
    mcp.run()


if __name__ == "__main__":
    main()
