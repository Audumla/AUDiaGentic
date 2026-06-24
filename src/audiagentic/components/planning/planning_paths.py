"""Path resolution for the planning component.

Paths are declared in each implementation descriptor's ``paths:`` block and
resolved via the features registry.  Falls back to defaults that match the
``planning-local-docs`` implementation so the API works even before the
registry is fully populated (e.g. during early bootstrap or tests).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_COMPONENT_ID = "agent-planning"

_DEFAULT_PATHS: dict[str, str] = {
    "plans-root": "docs/planning",
    "active-dir": "docs/planning/active",
    "completed-dir": "docs/planning/completed",
    "template": "docs/planning/TEMPLATE_ITEM.md",
}


def _active_implementation_id(project_root: Path) -> str:
    try:
        from audiagentic.foundation.features.registry import get_implementations
        from audiagentic.foundation.features.state import get_component_state
        component = get_component_state(project_root, _COMPONENT_ID)
        impls_state = component.get("implementations") or {}
        for impl_id, state in impls_state.items():
            if isinstance(state, dict) and state.get("enabled"):
                return impl_id
        all_impls = get_implementations(_COMPONENT_ID)
        for impl_id in sorted(all_impls):
            if all_impls[impl_id].raw.get("default"):
                return impl_id
        return next(iter(sorted(all_impls)), "planning-local-docs")
    except Exception:
        logger.debug("Could not resolve active planning implementation", exc_info=True)
        return "planning-local-docs"


def _load_paths(project_root: Path) -> dict[str, str]:
    try:
        from audiagentic.foundation.features.registry import get_implementation
        impl_id = _active_implementation_id(project_root)
        desc = get_implementation(_COMPONENT_ID, impl_id)
        if desc is not None:
            paths = desc.raw.get("paths")
            if paths:
                return paths
    except Exception:
        logger.debug("Could not load implementation paths from registry", exc_info=True)
    return dict(_DEFAULT_PATHS)


def _resolve(project_root: Path, key: str) -> Path:
    paths = _load_paths(project_root)
    value = paths.get(key) or _DEFAULT_PATHS.get(key, "")
    if not value:
        raise ValueError(f"Path key '{key}' not defined in planning implementation config")
    return project_root / value


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
