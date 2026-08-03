"""Planning item storage — paths, ID allocation, lookup, and cleanup.

Markdown round-trips go through the shared foundation frontmatter helpers;
this module owns only the planning-specific storage layout
(active/completed trees, ``<plan>/reviews/<parent>/`` nesting) and the
item/review guards shared by the CRUD modules.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from audiagentic.components.planning import planning_paths
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    transition_allowed,
)
from audiagentic.foundation.workflow.frontmatter import (
    build_sectioned_body,
    parse_custom_headings,
    parse_frontmatter,
    parse_sections,
    parse_title,
    render_frontmatter,
)

__all__ = [
    "ITEM_SECTION_HEADING",
    "HEADING_TO_FIELD",
    "FRONTMATTER_FIELDS",
    "METADATA_KEYS",
    "REVIEW_SECTIONS",
    "VALID_STATES",
    "active_states",
    "terminal_states",
    "append_change_log",
    "build_item_body",
    "check_transition",
    "cleanup_empty_plan_dirs",
    "dir_item_prefix",
    "ensure_not_review",
    "ensure_review",
    "find_item",
    "next_item_id",
    "next_review_id",
    "parse_change_log",
    "parse_frontmatter",
    "parse_item_custom_headings",
    "parse_item_sections",
    "parse_title",

    "render_item",
    "require_item",
    "state_dir",
]

logger = logging.getLogger(__name__)

VALID_STATES: set[str] = set()  # populated from workflows.yaml at import time

_WORKFLOWS_PATH = Path(__file__).with_name("workflows.yaml")

_PLANNING_YAML = Path(__file__).resolve().parents[2] / "config" / "components" / "planning.yaml"


def _load_valid_states() -> None:
    """Populate VALID_STATES from workflows.yaml item values."""
    global VALID_STATES  # noqa: PLW0603
    workflow = load_workflow(_WORKFLOWS_PATH, "item")
    VALID_STATES = set(workflow.get("values", []))


_load_valid_states()


def _load_config() -> None:
    """Load all config-driven constants from the planning component YAML."""
    cfg = load_yaml_file(_PLANNING_YAML)

    # Section heading maps (field_name → markdown heading)
    global ITEM_SECTION_HEADING, REVIEW_SECTIONS  # noqa: PLW0603
    ITEM_SECTION_HEADING = {k: v for k, v in cfg.get("item-section-headings", {}).items()}
    REVIEW_SECTIONS = {k: v for k, v in cfg.get("review-sections", {}).items()}

    # Derived reverse map (heading → field_name)
    global HEADING_TO_FIELD  # noqa: PLW0603
    HEADING_TO_FIELD = {v: k for k, v in ITEM_SECTION_HEADING.items()}

    # Frontmatter fields — metadata that lives in the YAML block, not body sections.
    global FRONTMATTER_FIELDS  # noqa: PLW0603
    FRONTMATTER_FIELDS = set(cfg.get("frontmatter-fields", []))

    # Metadata keys consumed during creation/update — never rendered as body sections.
    global METADATA_KEYS  # noqa: PLW0603
    METADATA_KEYS = set(cfg.get("metadata-keys", []))


# --- Config-driven constants (loaded from planning.yaml) ---
ITEM_SECTION_HEADING: dict[str, str] = {}
REVIEW_SECTIONS: dict[str, str] = {}
HEADING_TO_FIELD: dict[str, str] = {}
FRONTMATTER_FIELDS: set[str] = set()
METADATA_KEYS: set[str] = set()

_load_config()  # populate the above at import time

# --- Regex patterns ---
_ITEM_ID_RE = re.compile(r"^([A-Z]+)(\d+)$", re.IGNORECASE)
_CHANGE_LOG_HEADING = "## Change Log"
_CHANGE_ENTRY_RE = re.compile(r"^- (\S+) \(([^)]+)\): (.*)$")


def _get_state_set(kind: str, set_name: str) -> set[str]:
    """Return the state-sets value for a kind from workflows.yaml."""
    workflow = load_workflow(_WORKFLOWS_PATH, kind)
    return set(workflow.get("state-sets", {}).get(set_name, []))


def active_states(kind: str = "item") -> set[str]:
    """Return active (non-terminal) states for a kind from workflows.yaml."""
    return _get_state_set(kind, "active")


def terminal_states(kind: str = "item") -> set[str]:
    """Return terminal states for a kind from workflows.yaml."""
    return _get_state_set(kind, "terminal")


def check_transition(kind: str, old: str, new: str) -> None:
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


def state_dir(project_root: Path, state: str) -> Path:
    if state in active_states("item"):
        return planning_paths.plans_active_dir(project_root)
    if state in terminal_states("item"):
        return planning_paths.plans_completed_dir(project_root)
    raise AudiaGenticError(
        code="VAL-PLN-006",
        kind="validation",
        message=f"invalid state: {state!r}",
        details={"valid": sorted(VALID_STATES)},
    )


def parse_item_sections(body: str) -> dict[str, str]:
    """Parse an item body's title and known ``## Heading`` sections."""
    return parse_sections(body, HEADING_TO_FIELD)


def parse_item_custom_headings(body: str) -> dict[str, str]:
    """Return ``slug -> original heading`` for an item's non-standard sections.

    Pass the result to :func:`build_item_body` so custom headings survive a
    write unchanged instead of being rebuilt from their lossy slug.
    """
    return parse_custom_headings(body, HEADING_TO_FIELD)


def _serialize_section_value(value: Any) -> str:
    """Convert a section value to a markdown string.

    Strings pass through unchanged.  Dicts are rendered as nested bullet lists;
    lists become top-level bullet points.  Everything else falls back to ``str()``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        lines: list[str] = []
        for k, v in value.items():
            label = k.replace("_", " ").replace("-", " ").title()
            if isinstance(v, dict):
                indent_text = _serialize_section_value(v).replace("\n", "\n    ")
                lines.append(f"- **{label}**\n    {indent_text}")
            elif isinstance(v, list):
                sub = "\n".join(_bullet_items(v))
                indent_sub = sub.replace("\n", "\n    ")
                lines.append(f"- **{label}**\n    {indent_sub}")
            else:
                lines.append(f"- **{label}**: {v}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(_bullet_items(value))
    return str(value) if value is not None else ""


def _bullet_items(items: list[Any]) -> list[str]:
    """Render a list of items as markdown bullet points."""
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict):
            rendered = _serialize_section_value(item)
            indent = rendered.replace("\n", "\n    ")
            lines.append(f"- {indent}")
        elif isinstance(item, list):
            nested = _bullet_items(item)
            indent = "\n".join(nested).replace("\n", "\n    ")
            lines.append(f"- {indent}")
        else:
            lines.append(f"- {item}")
    return lines


def build_item_body(
    title: str,
    sections: dict[str, str],
    custom_headings: dict[str, str] | None = None,
) -> str:
    return build_sectioned_body(title, sections, ITEM_SECTION_HEADING, custom_headings)


def render_item(fm: dict[str, Any], body: str) -> str:
    return render_frontmatter(fm, body)





def dir_item_prefix(directory: Path) -> str | None:
    """Return the ID prefix already used by items in this directory, if any."""
    counts: dict[str, int] = {}
    if not directory.exists():
        return None
    for path in directory.glob("*.md"):
        match = _ITEM_ID_RE.match(path.stem)
        if match:
            prefix = match.group(1).upper()
            counts[prefix] = counts.get(prefix, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def next_item_id(project_root: Path, plan: str) -> str:
    """Auto-generate the next item ID for a plan using the plan prefix.

    Scans existing items in the plan and picks the next sequential number.
    E.g. for plan 'code-cleanup' → prefix 'CC', returns 'CC23' if CC22 is the max.

    The prefix is taken from IDs already used by items in this plan, since that
    is the authoritative record of the convention chosen when the plan was
    created — plan-name-derived guesses (e.g. slicing the slug) do not reliably
    reproduce a prefix chosen by a human (e.g. 'code-cleanup' -> 'CC' is initials,
    'process-lifecycle' -> 'PR' is not). Only plans with no items yet fall back to
    a guessed prefix, which is then checked for collisions against every other
    plan's prefix so a fresh guess can never silently alias an existing plan.
    """
    slug = plan
    active_dir = planning_paths.plans_active_dir(project_root) / slug
    completed_dir = planning_paths.plans_completed_dir(project_root) / slug

    prefix = dir_item_prefix(active_dir) or dir_item_prefix(completed_dir)
    if prefix is None:
        prefix = re.sub(r"[^A-Z]", "", slug[:2]).upper() or slug[:2].upper()
        _check_prefix_collision(project_root, slug, prefix)

    max_num = 0
    for directory in (active_dir, completed_dir):
        if not directory.exists():
            continue
        for path in directory.glob("*.md"):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", path.stem, re.IGNORECASE)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

    return f"{prefix}{max_num + 1:02d}"


def _check_prefix_collision(project_root: Path, slug: str, prefix: str) -> None:
    """Raise if a guessed prefix is already used by a different plan's items."""
    for root_dir in (
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ):
        if not root_dir.exists():
            continue
        for other_dir in root_dir.iterdir():
            if not other_dir.is_dir() or other_dir.name == slug:
                continue
            if dir_item_prefix(other_dir) == prefix:
                raise AudiaGenticError(
                    code="VAL-PLN-012",
                    kind="validation",
                    message=(
                        f"cannot auto-generate ID for plan {slug!r}: derived prefix "
                        f"{prefix!r} is already used by plan {other_dir.name!r}"
                    ),
                    details={"plan": slug, "prefix": prefix, "conflicting-plan": other_dir.name},
                )


def next_review_id(project_root: Path, slug: str, parent_id: str) -> str:
    """Auto-generate the next review ID (RV##).

    Review IDs are globally unique (the existence check in create_review scans
    every plan), so numbering must also be global: scanning only this plan's
    reviews would restart at RV01 for a plan's first review and collide with an
    RV01 owned by another plan. Scan all plans' review dirs and take the max.
    """
    max_num = 0
    for directory in (
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ):
        if not directory.exists():
            continue
        for path in directory.glob("*/reviews/**/*.md"):
            match = re.match(r"^RV(\d+)$", path.stem)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

    return f"RV{max_num + 1:02d}"


def find_item(project_root: Path, item_id: str) -> Path | None:
    for directory in (
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ):
        if directory.exists():
            for path in directory.rglob(f"{item_id}.md"):
                return path
    return None


def require_item(project_root: Path, item_id: str) -> Path:
    path = find_item(project_root, item_id)
    if path is None:
        raise AudiaGenticError(
            code="VAL-PLN-001",
            kind="validation",
            message=f"plan item not found: {item_id!r}",
        )
    return path


def ensure_not_review(fm: dict[str, Any], item_id: str, code: str) -> None:
    """Reject item-scoped operations (update_item/get_item/delete_item/set_state)
    against a review file.

    Reviews and plan items share the same filename-based lookup (find_item
    rglobs by <id>.md regardless of directory), and their body section
    templates are incompatible: an item has description/steps/files/
    validation/effort_risk/standards/notes, a review has notes/findings/
    conclusion. Rendering a review through the item template silently
    discards findings/conclusion and drops any updates keyed by
    review-only fields (they don't match any item section) — a real data-loss
    bug, not just a type mismatch. Fail loudly instead (Standard 8) rather
    than repeat that silently.
    """
    if "review-of" in fm:
        raise AudiaGenticError(
            code=code,
            kind="validation",
            message=f"{item_id!r} is a review, not a plan item — use the review-scoped tool instead",
            details={"id": item_id},
        )


def ensure_review(fm: dict[str, Any], review_id: str, code: str) -> None:
    """Reject review-scoped operations (update_review/get_review/delete_review)
    against a plain plan item — the symmetric case of ensure_not_review."""
    if "review-of" not in fm:
        raise AudiaGenticError(
            code=code,
            kind="validation",
            message=f"{review_id!r} is a plan item, not a review — use the item-scoped tool instead",
            details={"id": review_id},
        )


def _remove_empty_ancestors(dir_path: Path) -> None:
    """Recursively remove empty directories from dir_path up to (but not including) the state dir."""
    stop = dir_path.parent
    current = dir_path
    while current != stop and current.exists():
        try:
            current.rmdir()
            logger.debug("removed empty dir", extra={"dir": str(current)})
            current = current.parent
        except OSError:
            break


def _remove_empty_descendants(dir_path: Path) -> None:
    """Remove empty child directories below dir_path, deepest first."""
    if not dir_path.exists():
        return
    children = sorted(
        (path for path in dir_path.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for child in children:
        try:
            child.rmdir()
            logger.debug("removed empty child dir", extra={"dir": str(child)})
        except OSError:
            continue


def append_change_log(
    body: str,
    timestamp: str,
    actor: str,
    description: str,
) -> str:
    """Append a change-log entry to *body*.

    If the body already contains a ``## Change Log`` section, the new entry is
    appended as the last bullet.  Otherwise the section is created after all
    other sections.
    """
    entry = f"- {timestamp} ({actor}): {description}"
    if _CHANGE_LOG_HEADING in body:
        # Insert before the final newline of the Change Log section (which is the
        # end of the file for well-formed items).
        idx = body.rfind(_CHANGE_LOG_HEADING)
        section_text = body[idx:]
        # Append as a new line at the end of the section
        if not section_text.endswith("\n"):
            section_text += "\n"
        return body[:idx] + section_text + entry + "\n"
    else:
        # Create the section after all existing content
        return body.rstrip() + f"\n\n{_CHANGE_LOG_HEADING}\n\n{entry}\n"


def parse_change_log(body: str) -> list[dict[str, str]]:
    """Parse the ``## Change Log`` section from *body* into a list of entries.

    Each entry is a dict with keys ``timestamp``, ``actor``, and ``description``.
    Returns an empty list when no change log exists.
    """
    if _CHANGE_LOG_HEADING not in body:
        return []
    idx = body.index(_CHANGE_LOG_HEADING)
    section_text = body[idx:]
    entries: list[dict[str, str]] = []
    for line in section_text.splitlines():
        m = _CHANGE_ENTRY_RE.match(line.strip())
        if m:
            entries.append(
                {
                    "timestamp": m.group(1),
                    "actor": m.group(2),
                    "description": m.group(3),
                }
            )
    return entries


def cleanup_empty_plan_dirs(project_root: Path, slug: str, state_dirs: list[Path]) -> None:
    """Remove empty plan directories after item/review operations.

    If a plan directory has no items and no reviews remaining, remove it
    and any ancestor directories that become empty.
    """
    for directory in state_dirs:
        plan_dir = directory / slug
        if not plan_dir.exists():
            continue
        _remove_empty_descendants(plan_dir)
        has_items = any(plan_dir.glob("*.md"))
        has_reviews = any(plan_dir.glob("reviews/**/*.md"))
        if not has_items and not has_reviews:
            _remove_empty_ancestors(plan_dir)
            logger.info("removed empty plan dir", extra={"plan": slug, "state_dir": str(directory)})
