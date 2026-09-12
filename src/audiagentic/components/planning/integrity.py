"""Cross-record integrity checks for the local Markdown planning backend."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.planning import planning_paths
from audiagentic.components.planning.contracts import PlanningIntegrityError
from audiagentic.components.planning.identity import (
    validate_item_id,
    validate_plan_slug,
    validate_review_id,
)
from audiagentic.foundation.workflow.frontmatter import parse_frontmatter

_REVIEW_LINK_RE = re.compile(r"(?<![A-Za-z0-9])RV\d+(?![A-Za-z0-9])")
_ITEM_FILENAME_RE = re.compile(r"^[A-Z]+\d+$", re.IGNORECASE)
_REVIEW_FILENAME_RE = re.compile(r"^RV\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class ReviewContext:
    """A review plus the one canonical parent it is allowed to mutate."""

    review_path: Path
    review: dict[str, Any]
    parent_path: Path
    parent: dict[str, Any]


@dataclass(frozen=True)
class PlanningIntegrityIndex:
    """One snapshot of canonical item and review identities."""

    item_paths: dict[tuple[str, str], Path]
    items: dict[tuple[str, str], dict[str, Any]]
    review_paths: dict[str, Path]
    reviews: dict[str, dict[str, Any]]
    review_backlinks: dict[str, list[tuple[str, str]]]


def _item_paths(project_root: Path) -> list[Path]:
    paths: list[Path] = []
    for state_dir in (
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ):
        if not state_dir.exists():
            continue
        for path in state_dir.glob("*/*.md"):
            if not _ITEM_FILENAME_RE.fullmatch(path.stem):
                continue
            paths.append(planning_paths.assert_contained(state_dir, path))
    return sorted(paths)


def _review_paths(project_root: Path) -> list[Path]:
    paths: list[Path] = []
    for state_dir in (
        planning_paths.plans_active_dir(project_root),
        planning_paths.plans_completed_dir(project_root),
    ):
        if not state_dir.exists():
            continue
        for path in state_dir.glob("*/reviews/*/*.md"):
            if not _REVIEW_FILENAME_RE.fullmatch(path.stem):
                continue
            paths.append(planning_paths.assert_contained(state_dir, path))
    return sorted(paths)


def _read(path: Path) -> tuple[dict[str, Any], str]:
    try:
        return parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanningIntegrityError(f"cannot read planning record: {path}") from exc


def review_links(body: str) -> list[str]:
    """Return unique review IDs explicitly linked from an item body."""
    match = re.search(r"^##\s+Reviews\s*$", body, re.MULTILINE | re.IGNORECASE)
    if match:
        remainder = body[match.end() :]
        next_heading = re.search(r"^##\s+", remainder, re.MULTILINE)
        body = remainder[: next_heading.start()] if next_heading else remainder
    seen: set[str] = set()
    result: list[str] = []
    for review_id in _REVIEW_LINK_RE.findall(body):
        if review_id not in seen:
            seen.add(review_id)
            result.append(review_id)
    return result


def build_integrity_index(project_root: Path) -> PlanningIntegrityIndex:
    item_paths: dict[tuple[str, str], Path] = {}
    items: dict[tuple[str, str], dict[str, Any]] = {}
    review_paths: dict[str, Path] = {}
    reviews: dict[str, dict[str, Any]] = {}
    review_backlinks: dict[str, list[tuple[str, str]]] = {}
    item_ids: dict[str, tuple[str, str]] = {}

    for path in _item_paths(project_root):
        fm, body = _read(path)
        item_id = fm.get("id")
        plan = fm.get("plan")
        if not isinstance(item_id, str) or not isinstance(plan, str):
            raise PlanningIntegrityError(f"item has incomplete identity: {path}")
        try:
            validate_item_id(item_id)
            validate_plan_slug(plan)
        except Exception as exc:
            raise PlanningIntegrityError(f"item has invalid identity: {path}") from exc
        key = (plan, item_id)
        if key in item_paths:
            raise PlanningIntegrityError(f"duplicate item identity {plan}/{item_id}")
        if item_id in item_ids:
            raise PlanningIntegrityError(f"duplicate item identity {item_id}")
        if path.stem != item_id or path.parent.name != plan:
            raise PlanningIntegrityError(f"item path metadata mismatch: {path}")
        item_paths[key] = path
        item_ids[item_id] = key
        items[key] = {**fm, "_body": body}
        for review_id in review_links(body):
            review_backlinks.setdefault(review_id, []).append(key)

    for path in _review_paths(project_root):
        fm, body = _read(path)
        review_id = fm.get("id")
        plan = fm.get("plan")
        parent_id = fm.get("review-of")
        if not isinstance(review_id, str) or not isinstance(plan, str) or not isinstance(parent_id, str):
            raise PlanningIntegrityError(f"review has incomplete identity: {path}")
        validate_review_id(review_id)
        try:
            validate_plan_slug(plan)
            validate_item_id(parent_id)
        except Exception as exc:
            raise PlanningIntegrityError(f"review has invalid identity: {path}") from exc
        if review_id in review_paths:
            raise PlanningIntegrityError(f"duplicate review identity {review_id}")
        if (
            path.stem != review_id
            or path.parent.name != parent_id
            or path.parent.parent.parent.name != plan
        ):
            raise PlanningIntegrityError(f"review path metadata mismatch: {path}")
        review_paths[review_id] = path
        reviews[review_id] = {**fm, "_body": body}

    return PlanningIntegrityIndex(item_paths, items, review_paths, reviews, review_backlinks)


def require_canonical_review_context(
    project_root: Path,
    review_id: str,
    *,
    index: PlanningIntegrityIndex | None = None,
) -> ReviewContext:
    """Resolve and validate one review and its parent before mutation."""
    validate_review_id(review_id)
    snapshot = index or build_integrity_index(project_root)
    review_path = snapshot.review_paths.get(review_id)
    if review_path is None:
        raise PlanningIntegrityError(f"review not found in canonical index: {review_id}")
    review = snapshot.reviews[review_id]
    parent_id = review.get("review-of")
    plan = review.get("plan")
    if not isinstance(parent_id, str) or not isinstance(plan, str):
        raise PlanningIntegrityError(f"review has invalid parent metadata: {review_id}")
    validate_item_id(parent_id)
    parent_key = (plan, parent_id)
    parent_path = snapshot.item_paths.get(parent_key)
    if parent_path is None:
        raise PlanningIntegrityError(
            f"review {review_id} references missing parent {plan}/{parent_id}"
        )
    parent = snapshot.items[parent_key]
    if parent.get("id") != parent_id or parent.get("plan") != plan:
        raise PlanningIntegrityError(f"review parent metadata mismatch: {review_id}")
    backlinks = snapshot.review_backlinks.get(review_id, [])
    if backlinks != [parent_key]:
        raise PlanningIntegrityError(
            f"review {review_id} requires exactly one backlink from {plan}/{parent_id}; "
            f"found {backlinks}"
        )
    return ReviewContext(review_path, review, parent_path, parent)


def validate_repository_integrity(project_root: Path) -> list[str]:
    """Return all detected violations without mutating the repository.

    This audit intentionally reports legacy semantic defects instead of
    fabricating missing evidence. Runtime mutation APIs may still expose such
    records for repair, but must fail closed when they touch them.
    """
    errors: list[str] = []
    try:
        index = build_integrity_index(project_root)
    except PlanningIntegrityError as exc:
        return [str(exc)]

    for key, item in index.items.items():
        state = str(item.get("state", ""))
        if state == "completed":
            from audiagentic.components.planning import item_store

            sections = item_store.parse_item_sections(str(item.get("_body", "")))
            for field, label in (
                ("validation", "Validation"),
                ("acceptance_criteria", "Acceptance Criteria"),
            ):
                if not str(sections.get(field, "")).strip():
                    errors.append(f"{key[1]}: completed item requires {label}")
        for review_id in index.review_backlinks:
            if key in index.review_backlinks[review_id] and review_id not in index.reviews:
                errors.append(f"{key[1]} links missing review {review_id}")

    for review_id in index.reviews:
        try:
            require_canonical_review_context(project_root, review_id, index=index)
        except PlanningIntegrityError as exc:
            errors.append(str(exc))
    return errors


def assert_repository_integrity(project_root: Path) -> None:
    """Raise one deterministic integrity error when the repository is invalid."""
    errors = validate_repository_integrity(project_root)
    if errors:
        raise PlanningIntegrityError("; ".join(errors))


__all__ = [
    "PlanningIntegrityIndex",
    "ReviewContext",
    "build_integrity_index",
    "assert_repository_integrity",
    "require_canonical_review_context",
    "review_links",
    "validate_repository_integrity",
]
