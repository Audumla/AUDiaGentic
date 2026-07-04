"""Plan item CRUD and state transitions.

Storage layout, ID allocation, and markdown round-trips live in item_store.
"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.planning import item_store, planning_paths
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow.frontmatter import parse_frontmatter, parse_title

logger = logging.getLogger(__name__)


def create_item(project_root: Path, item: dict[str, Any]) -> dict[str, Any]:
    """Create a new plan item. Required keys: plan, title.

    If 'id' is not provided, it is auto-generated using the plan prefix
    and next available sequence number.
    """
    item_id = item.get("id")
    plan = item.get("plan")
    title = item.get("title")

    if not plan:
        raise AudiaGenticError(code="VAL-PLN-003", kind="validation", message="item 'plan' is required")
    if not title:
        raise AudiaGenticError(code="VAL-PLN-004", kind="validation", message="item 'title' is required")

    if not item_id:
        item_id = item_store.next_item_id(project_root, plan)

    if item_store.find_item(project_root, item_id) is not None:
        raise AudiaGenticError(
            code="VAL-PLN-005",
            kind="validation",
            message=f"plan item already exists: {item_id!r}",
        )

    fm: dict[str, Any] = {
        "id": item_id,
        "order": item.get("order", 0),
        "plan": item_store.plan_frontmatter_value(plan),
        "state": "pending",
        "validate-first": item.get("validate_first", True),
        "priority": item.get("priority", "P2"),
        "complexity": item.get("complexity", "simple"),
    }
    sections = {k: item.get(k, "") for k in item_store.ITEM_SECTION_HEADING}
    body = item_store.build_item_body(title, sections)

    slug = item_store.plan_slug(plan)
    target = planning_paths.plans_active_dir(project_root) / slug / f"{item_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(item_store.render_item(fm, body), encoding="utf-8")

    logger.info("plan item created", extra={"item_id": item_id, "plan": slug})
    return {
        "id": item_id,
        "title": title,
        "plan": slug,
        "path": str(target.relative_to(project_root)),
    }


def list_items(
    project_root: Path,
    state: str | None = None,
    plan: str | None = None,
    id_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """List plan items, optionally filtered by state, plan name, or ID prefix.

    state: 'active'/'pending'/'not_done' → active folder; 'completed' → completed folder; None → all.
    plan: directory name like 'code-cleanup' (omit for all plans). Supports
        glob wildcards (e.g. 'code-*') via fnmatch; a literal name matches
        only that plan, same as before.
    id_prefix: case-insensitive item-ID prefix (e.g. 'CC' matches CC01, CC20, ...).
    """
    if state in ("active", "pending", "not_done"):
        search_dirs = [planning_paths.plans_active_dir(project_root)]
    elif state == "completed":
        search_dirs = [planning_paths.plans_completed_dir(project_root)]
    else:
        search_dirs = [
            planning_paths.plans_active_dir(project_root),
            planning_paths.plans_completed_dir(project_root),
        ]

    slug = item_store.plan_slug(plan) if plan else None
    prefix = id_prefix.upper() if id_prefix else None
    results: list[dict[str, Any]] = []

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for path in sorted(search_dir.rglob("*.md")):
            if slug and not fnmatch.fnmatch(path.parent.name, slug):
                continue
            fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            item_id = fm.get("id", path.stem)
            if prefix and not str(item_id).upper().startswith(prefix):
                continue
            results.append({
                "id": item_id,
                "plan": fm.get("plan", ""),
                "state": fm.get("state", "pending"),
                "priority": fm.get("priority", ""),
                "complexity": fm.get("complexity", ""),
                "title": parse_title(body) or "",
                "path": str(path.relative_to(project_root)),
            })

    return results


def list_items_page(
    project_root: Path,
    state: str | None = None,
    plan: str | None = None,
    id_prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated, bounded item listing — the shape the plan_list_items MCP tool returns.

    ``list_items`` above returns the full unbounded match (needed internally by
    list_items_grouped/planning_status, which want the complete picture); this
    wraps it for tool callers, where an unbounded result over hundreds of items
    across active+completed plans can exceed the tool-response token budget.
    Two changes from list_items: state defaults to 'active' (open work only —
    pass state='all' to include completed items), and results are capped by
    limit/offset with a total count so a caller can page through the rest.
    """
    effective_state = state if state is not None else "active"
    query_state = None if effective_state == "all" else effective_state
    items = list_items(project_root, query_state, plan, id_prefix)
    total = len(items)
    page = items[offset:offset + limit] if limit else items[offset:]
    return {
        "items": page,
        "total": total,
        "returned": len(page),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < total,
    }


def list_items_grouped(
    project_root: Path,
    state: str | None = None,
    plan: str | None = None,
) -> list[dict[str, Any]]:
    """List plan items grouped by plan, with counts and items per group.

    Returns a list of plan groups, each containing the plan name, item count,
    and the list of items in that plan.
    """
    items = list_items(project_root, state, plan)

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        plan_key = item.get("plan", "ungrouped")
        if plan_key not in groups:
            groups[plan_key] = []
        groups[plan_key].append(item)

    result = []
    for plan_key, plan_items in sorted(groups.items()):
        active_count = sum(1 for i in plan_items if i["state"] in ("pending", "not_done"))
        completed_count = sum(1 for i in plan_items if i["state"] == "completed")
        result.append({
            "plan": plan_key,
            "item_count": len(plan_items),
            "active_count": active_count,
            "completed_count": completed_count,
            "items": plan_items,
        })

    return result


def get_item(project_root: Path, item_id: str) -> dict[str, Any]:
    """Read a plan item by ID, returning frontmatter + parsed body sections."""
    path = item_store.require_item(project_root, item_id)
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_not_review(fm, item_id, "VAL-PLN-018")
    sections = item_store.parse_item_sections(body)
    return {**fm, **sections, "path": str(path.relative_to(project_root))}


def set_state(project_root: Path, item_id: str, new_state: str) -> dict[str, Any]:
    """Transition item to new_state, moving to the appropriate folder."""
    target_dir = item_store.state_dir(project_root, new_state)  # raises on invalid state
    path = item_store.require_item(project_root, item_id)
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_not_review(fm, item_id, "VAL-PLN-019")

    # Normalise the stored state to the canonical name and validate the move
    canonical_state = "pending" if new_state in item_store.ACTIVE_STATES else "completed"
    item_store.check_transition("item", fm.get("state", "pending"), canonical_state)
    fm["state"] = canonical_state

    target = target_dir / path.parent.name / path.name
    if target != path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item_store.render_item(fm, body), encoding="utf-8")
        path.unlink()
    else:
        target.write_text(item_store.render_item(fm, body), encoding="utf-8")

    # Clean up empty plan dirs in the source state (item was moved away)
    source_dir = item_store.state_dir(
        project_root, "completed" if new_state in item_store.ACTIVE_STATES else "pending"
    )
    item_store.cleanup_empty_plan_dirs(project_root, path.parent.name, [source_dir])

    logger.info("plan item state changed", extra={"item_id": item_id, "state": canonical_state})
    return {"ok": True, "id": item_id, "state": canonical_state, "path": str(target.relative_to(project_root))}


def update_item(project_root: Path, item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update frontmatter fields and/or body sections of a plan item.

    Frontmatter keys: id, order, plan, state, validate-first, priority, complexity.
    Section keys: title, description, steps, files, validation, effort_risk, notes.
    """
    path = item_store.require_item(project_root, item_id)
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_not_review(fm, item_id, "VAL-PLN-020")
    sections = item_store.parse_item_sections(body)

    for key, value in updates.items():
        if key in item_store.FRONTMATTER_FIELDS:
            fm[key] = value
        elif key in item_store.ITEM_SECTION_HEADING or key == "title":
            sections[key] = value

    title = sections.pop("title", None)
    if title is None:
        title = parse_title(body) or item_id

    new_body = item_store.build_item_body(title, sections)
    path.write_text(item_store.render_item(fm, new_body), encoding="utf-8")

    logger.info("plan item updated", extra={"item_id": item_id})
    return {"ok": True, "id": item_id, "path": str(path.relative_to(project_root))}


def delete_item(project_root: Path, item_id: str) -> dict[str, Any]:
    """Permanently delete a plan item."""
    path = item_store.require_item(project_root, item_id)
    fm, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_not_review(fm, item_id, "VAL-PLN-021")
    slug = path.parent.name
    path.unlink()
    logger.info("plan item deleted", extra={"item_id": item_id})
    state_dirs = [
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ]
    item_store.cleanup_empty_plan_dirs(project_root, slug, state_dirs)
    return {"ok": True, "id": item_id}
