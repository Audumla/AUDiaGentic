"""Path resolution for the planning component.

Paths are declared in each implementation descriptor's ``paths:`` block and
resolved via the features registry.  Falls back to defaults that match the
``planning-local-docs`` implementation so the API works even before the
registry is fully populated (e.g. during early bootstrap or tests).
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError

_COMPONENT_ID = "agent-planning"

_DEFAULT_PATHS: dict[str, str] = {
    "plans-root": "docs/planning",
    "active-dir": "docs/planning/active",
    "completed-dir": "docs/planning/completed",
    "template": "docs/planning/TEMPLATE_ITEM.md",
}


def _resolve(project_root: Path, key: str) -> Path:
    from audiagentic.foundation.paths import resolve_component_path

    return resolve_component_path(project_root, _COMPONENT_ID, key, _DEFAULT_PATHS)


def plans_root(project_root: Path) -> Path:
    """Return the plans root directory (contains active/ and completed/)."""
    return _resolve(project_root, "plans-root")


def plans_active_dir(project_root: Path) -> Path:
    """Return the directory for pending plan items."""
    return _resolve(project_root, "active-dir")


def plans_completed_dir(project_root: Path) -> Path:
    """Return the directory for completed plan items."""
    return _resolve(project_root, "completed-dir")


def plans_template_path(project_root: Path) -> Path:
    """Return the plan item template file path."""
    return _resolve(project_root, "template")


def assert_contained(root: Path, candidate: Path) -> Path:
    """Return candidate only when its resolved path is below root."""
    resolved_root = root.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise AudiaGenticError(
            code="VAL-PLN-038",
            kind="validation",
            message="planning path escapes its configured root",
        ) from exc
    return resolved_candidate
