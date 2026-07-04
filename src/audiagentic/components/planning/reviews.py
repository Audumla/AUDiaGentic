"""Review CRUD and state transitions.

Reviews are items stored under the active/completed plan trees at:
  <state>/<plan>/reviews/<parent-id>/RV01.md
A review may target either a pending item in active/ or a completed item in
completed/; create_review resolves the parent across both trees, then creates
the new review in active/ until the review itself is closed.
Reviews use the same structure as regular items but with review-of frontmatter
and their own workflow (created → considered → closed), defined in workflows.yaml.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path
from typing import Any

from audiagentic.components.planning import item_store, planning_paths
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow.frontmatter import (
    build_sectioned_body,
    parse_frontmatter,
    parse_title,
)

logger = logging.getLogger(__name__)


def _parse_review_sections(body: str) -> dict[str, str]:
    """Extract review sections (notes/findings/conclusion), last occurrence wins."""
    sections: dict[str, str] = {}
    for key, heading in item_store.REVIEW_SECTIONS.items():
        matches = list(re.finditer(rf"^## {heading}\n\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL))
        if matches:
            sections[key] = matches[-1].group(1).strip()
    return sections


def create_review(project_root: Path, review: dict[str, Any]) -> dict[str, Any]:
    """Create a new review linked to a plan item.

    Required: review-of (parent item ID), title.
    Optional: notes, findings, conclusion, reviewed-by.
    Parent item may live in active/ or completed/.
    ID is auto-generated (e.g. RV01).
    Returns {id, title, review-of, plan, path}
    """
    review_id = review.get("id")
    parent_id = review.get("review-of") or review.get("review_of")
    title = review.get("title")

    if not parent_id:
        raise AudiaGenticError(code="VAL-PLN-008", kind="validation", message="review 'review-of' (or 'review_of') is required")
    if not title:
        raise AudiaGenticError(code="VAL-PLN-009", kind="validation", message="review 'title' is required")

    # Verify parent item exists
    parent_path = item_store.find_item(project_root, parent_id)
    if parent_path is None:
        raise AudiaGenticError(
            code="VAL-PLN-010",
            kind="validation",
            message=f"parent item not found: {parent_id!r}",
        )

    slug = parent_path.parent.name
    parent_fm, _ = parse_frontmatter(parent_path.read_text(encoding="utf-8"))

    if not review_id:
        review_id = item_store.next_review_id(project_root, slug, parent_path.stem)

    if item_store.find_item(project_root, review_id) is not None:
        raise AudiaGenticError(
            code="VAL-PLN-011",
            kind="validation",
            message=f"review already exists: {review_id!r}",
        )

    # Build frontmatter — reviews use review-of instead of plan prefix
    fm: dict[str, Any] = {
        "id": review_id,
        "review-of": parent_path.stem,
        "plan": parent_fm.get("plan", item_store.plan_frontmatter_value(slug)),
        "state": "created",
        "reviewed-by": review.get("reviewed-by", ""),
        "reviewed-at": review.get("reviewed-at", ""),
    }
    sections = {k: review.get(k, "") for k in item_store.REVIEW_SECTIONS}
    body = build_sectioned_body(title, sections, item_store.REVIEW_SECTIONS)

    target = (
        planning_paths.plans_active_dir(project_root)
        / slug
        / "reviews"
        / parent_path.stem
        / f"{review_id}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(item_store.render_item(fm, body), encoding="utf-8")

    logger.info("review created", extra={"review_id": review_id, "review_of": parent_id, "plan": slug})
    return {
        "id": review_id,
        "title": title,
        "review-of": parent_id,
        "plan": slug,
        "path": str(target.relative_to(project_root)),
    }


def list_reviews(
    project_root: Path,
    state: str | None = None,
    plan: str | None = None,
    review_of: str | None = None,
    id_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """List reviews, optionally filtered by state, plan, parent item, or ID prefix.

    state: 'created'/'considered'/'open' → active; 'closed' → completed; None → all.
    plan: directory name like 'code-cleanup' (omit for all plans). Supports
        glob wildcards (e.g. 'code-*') via fnmatch.
    review_of: parent item ID to filter by (omit for all).
    id_prefix: case-insensitive review-ID prefix (e.g. 'RV').
    """
    if state in ("created", "considered", "open"):
        search_dirs = [planning_paths.plans_active_dir(project_root)]
    elif state == "closed":
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
            # Reviews live under <plan>/reviews/<parent-id>/
            parts = path.relative_to(search_dir).parts
            if len(parts) < 3 or parts[1] != "reviews":
                continue
            if slug and not fnmatch.fnmatch(parts[0], slug):
                continue
            if review_of and parts[2] != review_of:
                continue
            fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            review_id = fm.get("id", path.stem)
            if prefix and not str(review_id).upper().startswith(prefix):
                continue
            results.append({
                "id": review_id,
                "review-of": fm.get("review-of", ""),
                "plan": fm.get("plan", ""),
                "state": fm.get("state", "created"),
                "reviewed-by": fm.get("reviewed-by", ""),
                "reviewed-at": fm.get("reviewed-at", ""),
                "title": parse_title(body) or "",
                "path": str(path.relative_to(project_root)),
            })

    return results


def list_reviews_page(
    project_root: Path,
    state: str | None = None,
    plan: str | None = None,
    review_of: str | None = None,
    id_prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated, bounded review listing — the shape the plan_list_reviews MCP tool returns.

    Mirrors list_items_page: state defaults to 'open' (created/considered,
    i.e. not yet closed) rather than everything, and results are capped by
    limit/offset with a total count.
    """
    effective_state = state if state is not None else "open"
    query_state = None if effective_state == "all" else effective_state
    reviews = list_reviews(project_root, query_state, plan, review_of, id_prefix)
    total = len(reviews)
    page = reviews[offset:offset + limit] if limit else reviews[offset:]
    return {
        "items": page,
        "total": total,
        "returned": len(page),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < total,
    }


def get_review(project_root: Path, review_id: str) -> dict[str, Any]:
    """Read a review by ID, returning frontmatter + parsed body sections."""
    path = item_store.require_item(project_root, review_id)
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_review(fm, review_id, "VAL-PLN-022")
    sections = item_store.parse_item_sections(body)
    sections.update(_parse_review_sections(body))
    title = parse_title(body)
    return {
        **fm,
        **sections,
        "title": fm.get("title", title if title else review_id),
        "path": str(path.relative_to(project_root)),
    }


def set_review_state(project_root: Path, review_id: str, new_state: str) -> dict[str, Any]:
    """Transition a review to a new state.

    'closed' moves the review to completed/.
    'created'/'considered' keep it in active/.
    Returns {id, state, path}
    """
    path = item_store.require_item(project_root, review_id)
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_review(fm, review_id, "VAL-PLN-013")
    item_store.check_transition("review", fm.get("state", "created"), new_state)

    slug = path.parent.parent.parent.name
    parent_id = path.parent.name
    source_state_dir = path.parent.parent.parent.parent

    target_dir = (
        planning_paths.plans_completed_dir(project_root)
        if new_state == "closed"
        else planning_paths.plans_active_dir(project_root)
    )
    fm["state"] = new_state
    target = target_dir / slug / "reviews" / parent_id / path.name
    if target != path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item_store.render_item(fm, body), encoding="utf-8")
        path.unlink()
    else:
        target.write_text(item_store.render_item(fm, body), encoding="utf-8")

    item_store.cleanup_empty_plan_dirs(project_root, slug, [source_state_dir])

    logger.info("review state changed", extra={"review_id": review_id, "state": new_state})
    return {"id": review_id, "state": new_state, "path": str(target.relative_to(project_root))}


def update_review(project_root: Path, review_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update frontmatter fields and/or body sections of a review.

    Frontmatter keys: reviewed-by, reviewed-at.
    Section keys: title, notes, findings, conclusion.
    Returns {id, path}
    """
    path = item_store.require_item(project_root, review_id)
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_review(fm, review_id, "VAL-PLN-023")
    title = parse_title(body) or review_id

    sections = _parse_review_sections(body)

    for key, value in updates.items():
        if key in ("reviewed-by", "reviewed-at", "review-of", "review_of", "id", "plan", "state"):
            fm[key] = value
        elif key in item_store.REVIEW_SECTIONS:
            sections[key] = value

    if "title" in updates:
        title = updates["title"]

    new_body = build_sectioned_body(title, sections, item_store.REVIEW_SECTIONS)
    path.write_text(item_store.render_item(fm, new_body), encoding="utf-8")

    logger.info("review updated", extra={"review_id": review_id})
    return {"id": review_id, "path": str(path.relative_to(project_root))}


def delete_review(project_root: Path, review_id: str) -> dict[str, Any]:
    """Permanently delete a review."""
    path = item_store.require_item(project_root, review_id)
    fm, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    item_store.ensure_review(fm, review_id, "VAL-PLN-024")
    slug = path.parent.parent.parent.name
    source_state_dir = path.parent.parent.parent.parent
    path.unlink()
    logger.info("review deleted", extra={"review_id": review_id})
    item_store.cleanup_empty_plan_dirs(project_root, slug, [source_state_dir])
    return {"id": review_id}
