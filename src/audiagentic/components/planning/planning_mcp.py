"""Planning MCP server — tools for managing plan items in docs/planning/."""

from __future__ import annotations

from typing import Any

from audiagentic.components.planning import planning_api
from audiagentic.components.planning.contracts import (
    ItemState,
    ItemStateFilter,
    Offset,
    PageLimit,
    PlanItemCreate,
    PlanItemUpdates,
    PlanReviewCreate,
    PlanReviewUpdates,
    ReviewState,
    ReviewStateFilter,
    ensure_model,
    model_mapping,
)
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def plan_create_item(item: PlanItemCreate) -> dict[str, Any]:
    """Create a plan item; custom sections are preserved."""
    return planning_api.create_item(project_root_from_env(), model_mapping(ensure_model(item, PlanItemCreate)))


@mcp.tool()
@tool_boundary
def plan_list_groups(
    state: ItemStateFilter | None = None,
    plan: str | None = None,
    limit: PageLimit = 20,
    offset: Offset = 0,
) -> dict[str, Any]:
    """List plan groups with bounded pagination."""
    groups = planning_api.list_items_grouped(project_root_from_env(), state, plan)
    page = groups[offset : offset + limit]
    return {
        "groups": page,
        "total": len(groups),
        "returned": len(page),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(groups),
    }


@mcp.tool()
@tool_boundary
def plan_list_items(
    plan: str | None = None,
    id_prefix: str | None = None,
    state: ItemStateFilter | None = None,
    limit: PageLimit = 20,
    offset: Offset = 0,
) -> dict[str, Any]:
    """List filtered plan items; provide ``plan`` or ``id_prefix``."""
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
def plan_get_item(item_id: str, include_history: bool = False) -> dict[str, Any]:
    """Read one plan item, optionally including change history."""
    return planning_api.get_item(project_root_from_env(), item_id, include_history)


@mcp.tool()
@tool_boundary
def plan_set_state(item_id: str, new_state: ItemState) -> dict[str, Any]:
    """Transition a plan item to a validated lifecycle state."""
    return planning_api.set_state(project_root_from_env(), item_id, new_state)


@mcp.tool()
@tool_boundary
def plan_update_item(
    item_id: str, updates: PlanItemUpdates, append: list[str] | None = None
) -> dict[str, Any]:
    """Update editable item fields; use ``append`` for additive sections."""
    return planning_api.update_item(
        project_root_from_env(), item_id, model_mapping(ensure_model(updates, PlanItemUpdates)), append
    )


@mcp.tool()
@tool_boundary
def plan_delete_item(item_id: str) -> dict[str, Any]:
    """Delete one plan item."""
    return planning_api.delete_item(project_root_from_env(), item_id)


@mcp.tool()
@tool_boundary
def plan_list_standards() -> list:
    """List configured planning standards."""
    return planning_api.list_standards(project_root_from_env())


# ---------------------------------------------------------------------------
# Review tools
# ---------------------------------------------------------------------------


@mcp.tool()
@tool_boundary
def plan_create_review(review: PlanReviewCreate) -> dict[str, Any]:
    """Create a review linked to an existing plan item."""
    return planning_api.create_review(
        project_root_from_env(), model_mapping(ensure_model(review, PlanReviewCreate))
    )


@mcp.tool()
@tool_boundary
def plan_list_reviews(
    state: ReviewStateFilter | None = None,
    plan: str | None = None,
    review_of: str | None = None,
    id_prefix: str | None = None,
    limit: PageLimit = 50,
    offset: Offset = 0,
) -> dict[str, Any]:
    """List filtered reviews with bounded pagination."""
    return planning_api.list_reviews_page(
        project_root_from_env(), state, plan, review_of, id_prefix, limit, offset
    )


@mcp.tool()
@tool_boundary
def plan_get_review(review_id: str) -> dict[str, Any]:
    """Read one review."""
    return planning_api.get_review(project_root_from_env(), review_id)


@mcp.tool()
@tool_boundary
def plan_set_review_state(review_id: str, new_state: ReviewState) -> dict[str, Any]:
    """Transition a review to a validated lifecycle state."""
    return planning_api.set_review_state(project_root_from_env(), review_id, new_state)


@mcp.tool()
@tool_boundary
def plan_update_review(review_id: str, updates: PlanReviewUpdates) -> dict[str, Any]:
    """Update review content without changing identity or state."""
    return planning_api.update_review(
        project_root_from_env(), review_id, model_mapping(ensure_model(updates, PlanReviewUpdates))
    )


@mcp.tool()
@tool_boundary
def plan_delete_review(review_id: str) -> dict[str, Any]:
    """Delete one review."""
    return planning_api.delete_review(project_root_from_env(), review_id)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap

    bootstrap("planning")
    mcp.run()


if __name__ == "__main__":
    main()
