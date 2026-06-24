"""Planning MCP server — tools for managing plan items in docs/planning/plans/."""
from __future__ import annotations

from audiagentic.components.planning import planning_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def plan_create_item(item: dict) -> dict:
    """Create a new plan item in docs/planning/plans/active/<plan>/.

    Required: id, plan, title.
    Optional: priority (P0/P1/P2/P3/HIGH/MEDIUM), complexity (simple/mid/complex),
              order, validate_first, description, steps, files, validation, effort_risk, notes.
    """
    return planning_api.create_item(project_root_from_env(), item)


@mcp.tool()
@log_tool_call
def plan_list_items(state: str | None = None, plan: str | None = None) -> list:
    """List plan items.

    state: 'active'/'pending' for active items, 'completed' for done, omit for all.
    plan: directory name like 'code-cleanup' (omit for all plans).
    """
    return planning_api.list_items(project_root_from_env(), state, plan)


@mcp.tool()
@log_tool_call
def plan_get_item(item_id: str) -> dict:
    """Read a plan item by ID, returning frontmatter and all body sections."""
    return planning_api.get_item(project_root_from_env(), item_id)


@mcp.tool()
@log_tool_call
def plan_set_state(item_id: str, new_state: str) -> dict:
    """Transition a plan item to a new state.

    new_state: 'pending' keeps item in active/; 'completed' moves it to completed/.
    """
    return planning_api.set_state(project_root_from_env(), item_id, new_state)


@mcp.tool()
@log_tool_call
def plan_update_item(item_id: str, updates: dict) -> dict:
    """Update frontmatter fields or body sections of a plan item.

    Frontmatter keys: order, plan, state, validate-first, priority, complexity.
    Body section keys: title, description, steps, files, validation, effort_risk, notes.
    """
    return planning_api.update_item(project_root_from_env(), item_id, updates)


@mcp.tool()
@log_tool_call
def plan_delete_item(item_id: str) -> dict:
    """Permanently delete a plan item by ID."""
    return planning_api.delete_item(project_root_from_env(), item_id)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("planning")
    mcp.run()


if __name__ == "__main__":
    main()
