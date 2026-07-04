"""Path resolution for the planning component.

Paths are declared in each implementation descriptor's ``paths:`` block and
resolved via the features registry.  Falls back to defaults that match the
``planning-local-docs`` implementation so the API works even before the
registry is fully populated (e.g. during early bootstrap or tests).
"""
from __future__ import annotations

from pathlib import Path

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
