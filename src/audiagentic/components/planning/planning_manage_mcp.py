"""Planning component management MCP server — status and implementation selection."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.features.lifecycle import enable_implementation
from audiagentic.foundation.features.registry import get_implementations, is_default_implementation
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    tool_boundary,
)

logger = logging.getLogger(__name__)

mcp = mcp_server(__name__)

_COMPONENT_ID = "agent-planning"


def _active_implementation(project_root: Path) -> str:
    """Return the enabled implementation ID, or the first registered default."""
    from audiagentic.components.planning.planning_api import active_implementation_id
    return active_implementation_id(project_root)


@mcp.tool()
@tool_boundary
def planning_status() -> dict[str, Any]:
    from audiagentic.components.planning.planning_api import planning_status as _status
    return _status(project_root_from_env()).to_dict()


@mcp.tool()
@tool_boundary
def planning_list_implementations() -> dict[str, Any]:
    root = project_root_from_env()
    impls = get_implementations(_COMPONENT_ID)
    return {
        "active": _active_implementation(root),
        "implementations": {
            impl_id: {
                "display_name": desc.display_name,
                "description": desc.description,
                "is_default": is_default_implementation(desc),
            }
            for impl_id, desc in impls.items()
        },
    }


@mcp.tool()
@tool_boundary
def planning_select_implementation(implementation: str) -> dict[str, Any]:
    root = project_root_from_env()
    return enable_implementation(root, _COMPONENT_ID, implementation)


@mcp.tool()
@tool_boundary
def planning_get_config(implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config plus the settable-option schema for an implementation.

    The ``schema`` field describes every option the implementation accepts
    (type, description, required, default, allowed values) — use it to
    discover what can be set, then pass any of those keys to
    ``planning_set_config``. Planning has no implementation-specific tools;
    all configuration goes through this generic get/set pair.
    """
    from audiagentic.components.planning.planning_api import planning_get_config as _get_config
    return _get_config(project_root_from_env(), implementation_id)


@mcp.tool()
@tool_boundary
def planning_set_config(implementation_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist config updates for a planning implementation.

    See ``planning_get_config`` for the option schema an implementation accepts.
    """
    from audiagentic.components.planning.planning_api import planning_set_config as _set_config
    return _set_config(project_root_from_env(), implementation_id, updates)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("planning-manage")
    mcp.run()


if __name__ == "__main__":
    main()
