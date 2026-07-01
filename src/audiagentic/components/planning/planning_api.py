"""Planning API — create, list, read, update, and transition plan items.

All paths are resolved via planning_paths, which reads from the active
implementation descriptor's ``paths:`` block.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from audiagentic.components.planning import planning_paths
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    transition_allowed,
)

logger = logging.getLogger(__name__)

_COMPONENT_ID = "agent-planning"

_VALID_STATES = {"pending", "completed"}
# 'not_done' is accepted as a legacy alias for 'pending'
_ACTIVE_STATES = {"pending", "not_done"}
_COMPLETED_STATES = {"completed"}

_WORKFLOWS_PATH = Path(__file__).with_name("workflows.yaml")


def active_implementation_id(project_root: Path) -> str:
    """Return the enabled implementation ID, or the descriptor-defined default."""
    from audiagentic.foundation.features.registry import get_implementations
    from audiagentic.foundation.features.state import get_component_state

    component = get_component_state(project_root, _COMPONENT_ID)
    implementations = component.get("implementations") or {}
    if isinstance(implementations, dict):
        for impl_id, state in implementations.items():
            if isinstance(state, dict) and state.get("enabled"):
                return impl_id
    impls = get_implementations(_COMPONENT_ID)
    for impl_id in sorted(impls):
        if impls[impl_id].raw.get("default"):
            return impl_id
    return next(iter(sorted(impls)), "")


def planning_status(project_root: Path) -> dict[str, Any]:
    """Return planning status: active implementation, item counts, config completeness.

    Configuration completeness is derived generically from the active
    implementation's options-schema via the shared features helper.
    """
    from audiagentic.foundation.features.config_status import implementation_config_status

    active = active_implementation_id(project_root)
    result: dict[str, Any] = {
        "implementation": active,
        "pending_items": len(list_items(project_root, state="active")),
        "completed_items": len(list_items(project_root, state="completed")),
    }
    if active:
        status = implementation_config_status(project_root, _COMPONENT_ID, active)
        result["enabled"] = status.enabled
        result["configured"] = status.configured
        if status.missing_required:
            result["missing_required"] = [
                {"option": m.key, "description": m.description}
                for m in status.missing_required
            ]
    return result


def _check_transition(kind: str, old: str, new: str) -> None:
    """Validate an ``old -> new`` state transition for a planning kind.

    States and legal transitions are defined in workflows.yaml; the shared
    foundation primitives enforce them. Same-state writes are treated as no-ops.
    """
    workflow = load_workflow(_WORKFLOWS_PATH, kind)
    if not is_known_state(workflow, new):
        raise AudiaGenticError(
            code="VAL-PLN-006",
            kind="validation",
            message=f"invalid {kind} state: {new!r}",
            details={"valid": list(workflow.get("values", []))},
        )
    if old != new and not transition_allowed(workflow, old, new):
        raise AudiaGenticError(
            code="VAL-PLN-014",
            kind="validation",
            message=f"illegal {kind} transition: {old} -> {new}",
            details={"from": old, "to": new},
        )

_SECTION_HEADING: dict[str, str] = {
    "description": "Description",
    "steps": "Steps",
    "files": "Files",
    "validation": "Validation",
    "effort_risk": "Effort & Risk",
    "standards": "Standards",
    "notes": "Notes",
}
_HEADING_TO_FIELD: dict[str, str] = {v: k for k, v in _SECTION_HEADING.items()}
_FRONTMATTER_FIELDS = {"id", "order", "plan", "state", "validate-first", "priority", "complexity"}
_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def _state_dir(project_root: Path, state: str) -> Path:
    if state in _ACTIVE_STATES:
        return planning_paths.plans_active_dir(project_root)
    if state in _COMPLETED_STATES:
        return planning_paths.plans_completed_dir(project_root)
    raise AudiaGenticError(
        code="VAL-PLN-006",
        kind="validation",
        message=f"invalid state: {state!r}",
        details={"valid": sorted(_VALID_STATES)},
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm: dict[str, Any] = yaml.safe_load(text[3:end].strip()) or {}
    body = text[end + 4:].lstrip("\n")
    return fm, body


def _parse_sections(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    title_match = re.match(r"^# (.+)$", body, re.MULTILINE)
    if title_match:
        result["title"] = title_match.group(1).strip()
    headings = list(_SECTION_RE.finditer(body))
    for i, match in enumerate(headings):
        field = _HEADING_TO_FIELD.get(match.group(1).strip())
        if field is None:
            continue
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        result[field] = body[start:end].strip()
    return result


def _build_body(title: str, sections: dict[str, str]) -> str:
    parts = [f"# {title}"]
    for key, heading in _SECTION_HEADING.items():
        content = sections.get(key, "")
        parts.append(f"\n## {heading}\n\n{content}")
    return "\n".join(parts) + "\n"


def _render_item(fm: dict[str, Any], body: str) -> str:
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{fm_str}\n---\n\n{body}"


def _plan_slug(plan: str) -> str:
    """Strip the 'plan-' prefix to get the directory name."""
    return plan.removeprefix("plan-")


def _plan_frontmatter_value(plan: str) -> str:
    """Ensure the frontmatter value carries the 'plan-' prefix."""
    return plan if plan.startswith("plan-") else f"plan-{plan}"


def _next_item_id(project_root: Path, plan: str) -> str:
    """Auto-generate the next item ID for a plan using the plan prefix.

    Scans existing items in the plan and picks the next sequential number.
    E.g. for plan 'code-cleanup' → prefix 'CC', returns 'CC07' if CC06 is the max.
    """
    plan_slug = _plan_slug(plan)
    active_dir = planning_paths.plans_active_dir(project_root) / plan_slug
    completed_dir = planning_paths.plans_completed_dir(project_root) / plan_slug

    # Extract prefix from the plan name (first 2 uppercase letters)
    prefix = re.sub(r'[^A-Z]', '', plan_slug[:2]).upper()
    if not prefix:
        prefix = plan_slug[:2].upper()

    max_num = 0
    for state_dir in (active_dir, completed_dir):
        if not state_dir.exists():
            continue
        for path in state_dir.glob("*.md"):
            stem = path.stem
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", stem, re.IGNORECASE)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

    return f"{prefix}{max_num + 1:02d}"


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


def _find_item(project_root: Path, item_id: str) -> Path | None:
    for state_dir in (
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ):
        if state_dir.exists():
            for path in state_dir.rglob(f"{item_id}.md"):
                return path
    return None


def _require_item(project_root: Path, item_id: str) -> Path:
    path = _find_item(project_root, item_id)
    if path is None:
        raise AudiaGenticError(
            code="VAL-PLN-001",
            kind="validation",
            message=f"plan item not found: {item_id!r}",
        )
    return path


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

    # Auto-generate ID if not provided
    if not item_id:
        item_id = _next_item_id(project_root, plan)

    if _find_item(project_root, item_id) is not None:
        raise AudiaGenticError(
            code="VAL-PLN-005",
            kind="validation",
            message=f"plan item already exists: {item_id!r}",
        )

    fm: dict[str, Any] = {
        "id": item_id,
        "order": item.get("order", 0),
        "plan": _plan_frontmatter_value(plan),
        "state": "pending",
        "validate-first": item.get("validate_first", True),
        "priority": item.get("priority", "P2"),
        "complexity": item.get("complexity", "simple"),
    }
    sections = {k: item.get(k, "") for k in _SECTION_HEADING}
    body = _build_body(title, sections)

    plan_slug = _plan_slug(plan)
    target = planning_paths.plans_active_dir(project_root) / plan_slug / f"{item_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_item(fm, body), encoding="utf-8")

    logger.info("plan item created", extra={"item_id": item_id, "plan": plan_slug})
    return {
        "id": item_id,
        "title": title,
        "plan": plan_slug,
        "path": str(target.relative_to(project_root)),
    }


def list_items(
    project_root: Path,
    state: str | None = None,
    plan: str | None = None,
) -> list[dict[str, Any]]:
    """List plan items, optionally filtered by state or plan name.

    state: 'active'/'pending'/'not_done' → active folder; 'completed' → completed folder; None → all.
    plan: directory name like 'code-cleanup' (omit for all plans).
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

    plan_slug = _plan_slug(plan) if plan else None
    results: list[dict[str, Any]] = []

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for path in sorted(search_dir.rglob("*.md")):
            if plan_slug and path.parent.name != plan_slug:
                continue
            text = path.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)
            title_match = re.match(r"^# (.+)$", body, re.MULTILINE)
            results.append({
                "id": fm.get("id", path.stem),
                "plan": fm.get("plan", ""),
                "state": fm.get("state", "pending"),
                "priority": fm.get("priority", ""),
                "complexity": fm.get("complexity", ""),
                "title": title_match.group(1).strip() if title_match else "",
                "path": str(path.relative_to(project_root)),
            })

    return results


def get_item(project_root: Path, item_id: str) -> dict[str, Any]:
    """Read a plan item by ID, returning frontmatter + parsed body sections."""
    path = _require_item(project_root, item_id)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    sections = _parse_sections(body)
    return {**fm, **sections, "path": str(path.relative_to(project_root))}


def set_state(project_root: Path, item_id: str, new_state: str) -> dict[str, Any]:
    """Transition item to new_state, moving to the appropriate folder."""
    target_dir = _state_dir(project_root, new_state)  # raises on invalid state
    path = _require_item(project_root, item_id)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)

    # Normalise the stored state to the canonical name and validate the move
    canonical_state = "pending" if new_state in _ACTIVE_STATES else "completed"
    _check_transition("item", fm.get("state", "pending"), canonical_state)
    fm["state"] = canonical_state

    target = target_dir / path.parent.name / path.name
    if target != path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_item(fm, body), encoding="utf-8")
        path.unlink()
    else:
        target.write_text(_render_item(fm, body), encoding="utf-8")

    # Clean up empty plan dirs in the source state (item was moved away)
    source_dir = _state_dir(project_root, "completed" if new_state in _ACTIVE_STATES else "pending")
    _cleanup_empty_plan_dirs(project_root, path.parent.name, [source_dir])

    logger.info("plan item state changed", extra={"item_id": item_id, "state": canonical_state})
    return {"ok": True, "id": item_id, "state": canonical_state, "path": str(target.relative_to(project_root))}


def update_item(project_root: Path, item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update frontmatter fields and/or body sections of a plan item.

    Frontmatter keys: id, order, plan, state, validate-first, priority, complexity.
    Section keys: title, description, steps, files, validation, effort_risk, notes.
    """
    path = _require_item(project_root, item_id)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    sections = _parse_sections(body)

    for key, value in updates.items():
        if key in _FRONTMATTER_FIELDS:
            fm[key] = value
        elif key in _SECTION_HEADING or key == "title":
            sections[key] = value

    title = sections.pop("title", None)
    if title is None:
        match = re.match(r"^# (.+)$", body, re.MULTILINE)
        title = match.group(1).strip() if match else item_id

    new_body = _build_body(title, sections)
    path.write_text(_render_item(fm, new_body), encoding="utf-8")

    logger.info("plan item updated", extra={"item_id": item_id})
    return {"ok": True, "id": item_id, "path": str(path.relative_to(project_root))}


def _remove_empty_ancestors(dir_path: Path) -> None:
    """Recursively remove empty directories from dir_path up to (but not including) state_dir."""
    state_dir = dir_path.parent
    current = dir_path
    while current != state_dir and current.exists():
        try:
            current.rmdir()
            logger.debug("removed empty dir", extra={"dir": str(current)})
            current = current.parent
        except OSError:
            break


def _cleanup_empty_plan_dirs(project_root: Path, plan_slug: str, state_dirs: list[Path]) -> None:
    """Remove empty plan directories after item/review operations.

    If a plan directory has no items and no reviews remaining, remove it
    and any ancestor directories that become empty.
    """
    for state_dir in state_dirs:
        plan_dir = state_dir / plan_slug
        if not plan_dir.exists():
            continue
        has_items = any(plan_dir.glob("*.md"))
        has_reviews = any(plan_dir.glob("reviews/**/*.md"))
        if not has_items and not has_reviews:
            _remove_empty_ancestors(plan_dir)
            logger.info("removed empty plan dir", extra={"plan": plan_slug, "state_dir": str(state_dir)})


def delete_item(project_root: Path, item_id: str) -> dict[str, Any]:
    """Permanently delete a plan item."""
    path = _require_item(project_root, item_id)
    plan_slug = path.parent.name
    path.unlink()
    logger.info("plan item deleted", extra={"item_id": item_id})
    state_dirs = [
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ]
    _cleanup_empty_plan_dirs(project_root, plan_slug, state_dirs)
    return {"ok": True, "id": item_id}


# ---------------------------------------------------------------------------
# Review support
# ---------------------------------------------------------------------------

# Reviews are items stored in active/<plan>/reviews/<parent-id>/RV01.md
# They use the same structure as regular items but with review-of frontmatter
# and their own workflow (created → considered → closed), defined in workflows.yaml.


def _next_review_id(project_root: Path, plan_slug: str, parent_id: str) -> str:
    """Auto-generate the next review ID (RV##) for an item within a plan."""
    active_reviews_dir = planning_paths.plans_active_dir(project_root) / plan_slug / "reviews"
    completed_reviews_dir = planning_paths.plans_completed_dir(project_root) / plan_slug / "reviews"

    max_num = 0
    for state_dir in (active_reviews_dir, completed_reviews_dir):
        if not state_dir.exists():
            continue
        for path in state_dir.rglob("*.md"):
            match = re.match(r"^RV(\d+)$", path.stem)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

    return f"RV{max_num + 1:02d}"


def create_review(project_root: Path, review: dict[str, Any]) -> dict[str, Any]:
    """Create a new review linked to a plan item.

    Required: review-of (parent item ID), title.
    Optional: notes, findings, conclusion, reviewed-by.
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
    parent_path = _find_item(project_root, parent_id)
    if parent_path is None:
        raise AudiaGenticError(
            code="VAL-PLN-010",
            kind="validation",
            message=f"parent item not found: {parent_id!r}",
        )

    plan_slug = parent_path.parent.name
    parent_fm, _ = _parse_frontmatter(parent_path.read_text(encoding="utf-8"))

    # Auto-generate ID if not provided
    if not review_id:
        review_id = _next_review_id(project_root, plan_slug, parent_path.stem)

    if _find_item(project_root, review_id) is not None:
        raise AudiaGenticError(
            code="VAL-PLN-011",
            kind="validation",
            message=f"review already exists: {review_id!r}",
        )

    # Build frontmatter — reviews use review-of instead of plan prefix
    fm: dict[str, Any] = {
        "id": review_id,
        "review-of": parent_path.stem,
        "plan": parent_fm.get("plan", _plan_frontmatter_value(plan_slug)),
        "state": "created",
        "reviewed-by": review.get("reviewed-by", ""),
        "reviewed-at": review.get("reviewed-at", ""),
    }
    # Reviews use notes, findings, conclusion sections
    _REVIEW_SECTIONS = {"notes": "Notes", "findings": "Findings", "conclusion": "Conclusion"}
    sections = {k: review.get(k, "") for k in _REVIEW_SECTIONS}
    parts = [f"# {title}"]
    for key, heading in _REVIEW_SECTIONS.items():
        content = sections.get(key, "")
        parts.append(f"\n## {heading}\n\n{content}")
    body = "\n".join(parts) + "\n"

    target = (
        planning_paths.plans_active_dir(project_root)
        / plan_slug
        / "reviews"
        / parent_path.stem
        / f"{review_id}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_item(fm, body), encoding="utf-8")

    logger.info("review created", extra={"review_id": review_id, "review_of": parent_id, "plan": plan_slug})
    return {
        "id": review_id,
        "title": title,
        "review-of": parent_id,
        "plan": plan_slug,
        "path": str(target.relative_to(project_root)),
    }


def list_reviews(
    project_root: Path,
    state: str | None = None,
    plan: str | None = None,
    review_of: str | None = None,
) -> list[dict[str, Any]]:
    """List reviews, optionally filtered by state, plan, or parent item.

    state: 'created'/'considered' → active; 'closed' → completed; None → all.
    plan: directory name like 'code-cleanup' (omit for all plans).
    review_of: parent item ID to filter by (omit for all).
    """
    if state in ("created", "considered"):
        search_dirs = [planning_paths.plans_active_dir(project_root)]
    elif state == "closed":
        search_dirs = [planning_paths.plans_completed_dir(project_root)]
    else:
        search_dirs = [
            planning_paths.plans_active_dir(project_root),
            planning_paths.plans_completed_dir(project_root),
        ]

    plan_slug = _plan_slug(plan) if plan else None
    results: list[dict[str, Any]] = []

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for path in sorted(search_dir.rglob("*.md")):
            # Reviews live under <plan>/reviews/<parent-id>/
            parts = path.relative_to(search_dir).parts
            if len(parts) < 3 or parts[1] != "reviews":
                continue
            if plan_slug and parts[0] != plan_slug:
                continue
            if review_of and parts[2] != review_of:
                continue
            text = path.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)
            title_match = re.match(r"^# (.+)$", body, re.MULTILINE)
            results.append({
                "id": fm.get("id", path.stem),
                "review-of": fm.get("review-of", ""),
                "plan": fm.get("plan", ""),
                "state": fm.get("state", "created"),
                "reviewed-by": fm.get("reviewed-by", ""),
                "reviewed-at": fm.get("reviewed-at", ""),
                "title": title_match.group(1).strip() if title_match else "",
                "path": str(path.relative_to(project_root)),
            })

    return results


def set_review_state(project_root: Path, review_id: str, new_state: str) -> dict[str, Any]:
    """Transition a review to a new state.

    'closed' moves the review to completed/.
    'created'/'considered' keep it in active/.
    Returns {id, state, path}
    """
    path = _require_item(project_root, review_id)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    # Only allow state transitions on reviews (has review-of frontmatter)
    if "review-of" not in fm:
        raise AudiaGenticError(
            code="VAL-PLN-013",
            kind="validation",
            message=f"not a review: {review_id!r}",
        )
    _check_transition("review", fm.get("state", "created"), new_state)

    plan_slug = path.parent.parent.parent.name
    parent_id = path.parent.name

    target_dir = (
        planning_paths.plans_completed_dir(project_root)
        if new_state == "closed"
        else planning_paths.plans_active_dir(project_root)
    )
    fm["state"] = new_state
    target = target_dir / plan_slug / "reviews" / parent_id / path.name
    if target != path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_item(fm, body), encoding="utf-8")
        path.unlink()
    else:
        target.write_text(_render_item(fm, body), encoding="utf-8")

    logger.info("review state changed", extra={"review_id": review_id, "state": new_state})
    return {"id": review_id, "state": new_state, "path": str(target.relative_to(project_root))}


def get_review(project_root: Path, review_id: str) -> dict[str, Any]:
    """Read a review by ID, returning frontmatter + parsed body sections."""
    path = _require_item(project_root, review_id)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    title_match = re.match(r"^# (.+)$", body, re.MULTILINE)
    sections = _parse_sections(body)
    # Reviews also have findings and conclusion sections
    for heading in ("Findings", "Conclusion"):
        matches = list(re.finditer(rf"^## {heading}\n\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL))
        if matches:
            sections[heading.lower()] = matches[-1].group(1).strip()
    return {
        **fm,
        **sections,
        "title": fm.get("title", title_match.group(1).strip() if title_match else review_id),
        "path": str(path.relative_to(project_root)),
    }


def update_review(project_root: Path, review_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update frontmatter fields and/or body sections of a review.

    Frontmatter keys: reviewed-by, reviewed-at.
    Section keys: title, notes, findings, conclusion.
    Returns {id, path}
    """
    path = _require_item(project_root, review_id)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    title_match = re.match(r"^# (.+)$", body, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else review_id

    # Parse review-specific sections
    _REVIEW_SECTIONS = {"notes": "Notes", "findings": "Findings", "conclusion": "Conclusion"}
    sections: dict[str, str] = {}
    for key, heading in _REVIEW_SECTIONS.items():
        matches = list(re.finditer(rf"^## {heading}\n\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL))
        if matches:
            sections[key] = matches[-1].group(1).strip()

    for key, value in updates.items():
        if key in ("reviewed-by", "reviewed-at", "review-of", "review_of", "id", "plan", "state"):
            fm[key] = value
        elif key in _REVIEW_SECTIONS or key == "title":
            sections[key] = value
        elif key == "title":
            title = value

    if "title" in updates:
        title = updates["title"]

    # Build review body
    parts = [f"# {title}"]
    for key, heading in _REVIEW_SECTIONS.items():
        content = sections.get(key, "")
        parts.append(f"\n## {heading}\n\n{content}")
    new_body = "\n".join(parts) + "\n"
    path.write_text(_render_item(fm, new_body), encoding="utf-8")

    logger.info("review updated", extra={"review_id": review_id})
    return {"id": review_id, "path": str(path.relative_to(project_root))}


def delete_review(project_root: Path, review_id: str) -> dict[str, Any]:
    """Permanently delete a review."""
    path = _require_item(project_root, review_id)
    path.unlink()
    logger.info("review deleted", extra={"review_id": review_id})
    return {"id": review_id}


# ---------------------------------------------------------------------------
# Standards support
# ---------------------------------------------------------------------------

def list_standards(project_root: Path) -> list[dict[str, Any]]:
    """List architecture and design standards from implementation config.

    Reads the standards list from the active implementation descriptor's YAML.
    Returns a list of dicts with id, title, path, and description fields.
    """
    try:
        from audiagentic.foundation.features.registry import get_implementation
        impl_id = "planning-local-docs"
        desc = get_implementation("agent-planning", impl_id)
        if desc is not None:
            standards = desc.raw.get("standards", [])
            if standards:
                return standards
    except Exception:
        logger.debug("Could not load standards from implementation config", exc_info=True)
    return []
