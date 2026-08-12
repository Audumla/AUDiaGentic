"""Planning MCP server — tools for managing plan items in docs/planning/."""

from __future__ import annotations

from audiagentic.components.planning import planning_api
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def plan_create_item(item: dict) -> dict:
    return planning_api.create_item(project_root_from_env(), item)


@mcp.tool()
@tool_boundary
def plan_list_groups(state: str | None = None, plan: str | None = None) -> list:
    return planning_api.list_items_grouped(project_root_from_env(), state, plan)


@mcp.tool()
@tool_boundary
def plan_list_items(
    plan: str | None = None,
    id_prefix: str | None = None,
    state: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List plan items, bounded and paginated.

    At least one of ``plan`` or ``id_prefix`` is required — unbounded scans
    are not allowed.  ``plan`` accepts a single plan name (e.g. 'code-cleanup')
    or a glob wildcard (e.g. 'code-*').  ``id_prefix`` filters by item-ID
    prefix (e.g. 'CC' matches CC01, CC20).  ``state`` defaults to 'active'
    (open work only) — pass state='completed' or state='all' to see closed
    items.

    Returns {items, total, returned, offset, limit, has_more}; page through
    results with offset when has_more is true.  Default limit is 20.

    When id_prefix is provided and no items match the current state filter,
    matching items from other states are returned as overflow_items with a
    note explaining why — so you know the item exists but is in a different
    state (e.g. completed instead of active).
    """
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    if plan is None and id_prefix is None:
        raise AudiaGenticError(
            code="VAL-PLN-026",
            kind="validation",
            message=(
                "plan_list_items requires at least one of 'plan' or 'id_prefix'."
                " Use plan='code-cleanup' to filter by plan, or id_prefix='CC'"
                " to filter by ID prefix."
            ),
        )
    return planning_api.list_items_page(
        project_root_from_env(), state, plan, id_prefix, limit, offset
    )


@mcp.tool()
@tool_boundary
def plan_get_item(
    item_id: str,
    include_history: bool = False,
) -> dict:
    """Read a plan item by ID, returning frontmatter and all body sections.

    Set include_history=True to also get the change-log entries as a list of
    {timestamp, actor, description} dicts under the 'change_log' key.  Default
    is False — callers that need audit history must opt in.
    """
    return planning_api.get_item(project_root_from_env(), item_id, include_history)


@mcp.tool()
@tool_boundary
def plan_set_state(item_id: str, new_state: str) -> dict:
    return planning_api.set_state(project_root_from_env(), item_id, new_state)


@mcp.tool()
@tool_boundary
def plan_update_item(item_id: str, updates: dict) -> dict:
    return planning_api.update_item(project_root_from_env(), item_id, updates)


@mcp.tool()
@tool_boundary
def plan_delete_item(item_id: str) -> dict:
    return planning_api.delete_item(project_root_from_env(), item_id)


@mcp.tool()
@tool_boundary
def plan_list_standards() -> list:
    return planning_api.list_standards(project_root_from_env())


# ---------------------------------------------------------------------------
# Review tools
# ---------------------------------------------------------------------------


@mcp.tool()
@tool_boundary
def plan_create_review(review: dict) -> dict:
    return planning_api.create_review(project_root_from_env(), review)


@mcp.tool()
@tool_boundary
def plan_list_reviews(
    state: str | None = None,
    plan: str | None = None,
    review_of: str | None = None,
    id_prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List reviews, bounded and paginated.

    state defaults to 'open' (created/considered — not yet closed) — pass
    state='closed' or state='all' to see closed reviews. plan accepts glob
    wildcards (e.g. 'code-*'). id_prefix filters by review-ID prefix (e.g.
    'RV'). Returns {items, total, returned, offset, limit, has_more}; page
    through results with offset when has_more is true.

    When id_prefix is provided and no reviews match the current state filter,
    matching reviews from other states are returned as overflow_items with a
    note explaining why — so you know the review exists but is in a different
    state (e.g. closed instead of open).
    """
    return planning_api.list_reviews_page(
        project_root_from_env(), state, plan, review_of, id_prefix, limit, offset
    )


@mcp.tool()
@tool_boundary
def plan_get_review(review_id: str) -> dict:
    return planning_api.get_review(project_root_from_env(), review_id)


@mcp.tool()
@tool_boundary
def plan_set_review_state(review_id: str, new_state: str) -> dict:
    return planning_api.set_review_state(project_root_from_env(), review_id, new_state)


@mcp.tool()
@tool_boundary
def plan_update_review(review_id: str, updates: dict) -> dict:
    return planning_api.update_review(project_root_from_env(), review_id, updates)


@mcp.tool()
@tool_boundary
def plan_delete_review(review_id: str) -> dict:
    return planning_api.delete_review(project_root_from_env(), review_id)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap

    bootstrap("planning")
    mcp.run()


if __name__ == "__main__":
    main()
