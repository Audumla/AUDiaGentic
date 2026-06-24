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

logger = logging.getLogger(__name__)

_VALID_STATES = {"pending", "completed"}
# 'not_done' is accepted as a legacy alias for 'pending'
_ACTIVE_STATES = {"pending", "not_done"}
_COMPLETED_STATES = {"completed"}

_SECTION_HEADING: dict[str, str] = {
    "description": "Description",
    "steps": "Steps",
    "files": "Files",
    "validation": "Validation",
    "effort_risk": "Effort & Risk",
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


def _list_items_grouped(
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
    """Create a new plan item. Required keys: id, plan, title."""
    item_id = item.get("id")
    plan = item.get("plan")
    title = item.get("title")

    if not item_id:
        raise AudiaGenticError(code="VAL-PLN-002", kind="validation", message="item 'id' is required")
    if not plan:
        raise AudiaGenticError(code="VAL-PLN-003", kind="validation", message="item 'plan' is required")
    if not title:
        raise AudiaGenticError(code="VAL-PLN-004", kind="validation", message="item 'title' is required")

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
    return {"ok": True, "id": item_id, "path": str(target.relative_to(project_root))}


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

    # Normalise the stored state to the canonical name
    canonical_state = "pending" if new_state in _ACTIVE_STATES else "completed"
    fm["state"] = canonical_state

    target = target_dir / path.parent.name / path.name
    if target != path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_item(fm, body), encoding="utf-8")
        path.unlink()
    else:
        target.write_text(_render_item(fm, body), encoding="utf-8")

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

    title = sections.pop("title", None) or re.match(r"^# (.+)$", body, re.MULTILINE)
    if hasattr(title, "group"):
        title = title.group(1).strip()  # type: ignore[union-attr]

    new_body = _build_body(title or item_id, sections)
    path.write_text(_render_item(fm, new_body), encoding="utf-8")

    logger.info("plan item updated", extra={"item_id": item_id})
    return {"ok": True, "id": item_id, "path": str(path.relative_to(project_root))}


def delete_item(project_root: Path, item_id: str) -> dict[str, Any]:
    """Permanently delete a plan item."""
    path = _require_item(project_root, item_id)
    path.unlink()
    logger.info("plan item deleted", extra={"item_id": item_id})
    return {"ok": True, "id": item_id}
