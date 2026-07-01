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
    return planning_api.create_item(project_root_from_env(), item)


@mcp.tool()
@log_tool_call
def plan_list_groups(state: str | None = None, plan: str | None = None) -> list:
    return planning_api.list_items_grouped(project_root_from_env(), state, plan)


@mcp.tool()
@log_tool_call
def plan_list_items(state: str | None = None, plan: str | None = None) -> list:
    return planning_api.list_items(project_root_from_env(), state, plan)


@mcp.tool()
@log_tool_call
def plan_get_item(item_id: str) -> dict:
    return planning_api.get_item(project_root_from_env(), item_id)


@mcp.tool()
@log_tool_call
def plan_set_state(item_id: str, new_state: str) -> dict:
    return planning_api.set_state(project_root_from_env(), item_id, new_state)


@mcp.tool()
@log_tool_call
def plan_update_item(item_id: str, updates: dict) -> dict:
    return planning_api.update_item(project_root_from_env(), item_id, updates)


@mcp.tool()
@log_tool_call
def plan_delete_item(item_id: str) -> dict:
    return planning_api.delete_item(project_root_from_env(), item_id)


@mcp.tool()
@log_tool_call
def plan_list_standards() -> list:
    return planning_api.list_standards(project_root_from_env())


# ---------------------------------------------------------------------------
# Review tools
# ---------------------------------------------------------------------------

@mcp.tool()
@log_tool_call
def plan_create_review(review: dict) -> dict:
    return planning_api.create_review(project_root_from_env(), review)


@mcp.tool()
@log_tool_call
def plan_list_reviews(
    state: str | None = None,
    plan: str | None = None,
    review_of: str | None = None,
) -> list:
    return planning_api.list_reviews(project_root_from_env(), state, plan, review_of)


@mcp.tool()
@log_tool_call
def plan_get_review(review_id: str) -> dict:
    return planning_api.get_review(project_root_from_env(), review_id)


@mcp.tool()
@log_tool_call
def plan_set_review_state(review_id: str, new_state: str) -> dict:
    return planning_api.set_review_state(project_root_from_env(), review_id, new_state)


@mcp.tool()
@log_tool_call
def plan_update_review(review_id: str, updates: dict) -> dict:
    return planning_api.update_review(project_root_from_env(), review_id, updates)


@mcp.tool()
@log_tool_call
def plan_delete_review(review_id: str) -> dict:
    return planning_api.delete_review(project_root_from_env(), review_id)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("planning")
    mcp.run()


if __name__ == "__main__":
    main()
