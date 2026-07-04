"""Component-declared path resolution.

Components declare named paths in YAML — either in the active implementation
descriptor's ``paths:`` block (features registry) or in the installed
component config's ``paths:`` block (.audiagentic/components/<id>.yaml).
This module is the single resolver for that pattern; components keep only a
defaults dict and thin public accessors.

Resolution precedence per key:
  1. active implementation descriptor's ``paths:`` block, when the component
     declares implementations;
  2. the installed component config YAML's ``paths:`` block;
  3. the caller-supplied defaults dict.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error

logger = logging.getLogger(__name__)


def _implementation_paths(project_root: Path, component_id: str) -> dict[str, str] | None:
    """Return the active implementation descriptor's paths block, if any."""
    try:
        from audiagentic.foundation.features.registry import (
            get_implementation,
            resolve_active_implementation,
        )

        impl_id = resolve_active_implementation(project_root, component_id)
        if not impl_id:
            return None
        desc = get_implementation(component_id, impl_id)
        if desc is not None:
            paths = desc.raw.get("paths")
            if paths:
                return paths
    except Exception:
        logger.debug(
            "Could not load implementation paths for %s", component_id, exc_info=True
        )
    return None


def _component_config_paths(project_root: Path, component_id: str) -> dict[str, str] | None:
    """Return the installed component config's paths block, if any."""
    config_path = project_root / ".audiagentic" / "components" / f"{component_id}.yaml"
    if not config_path.exists():
        return None
    try:
        from audiagentic.foundation.io import load_yaml_file

        config: dict[str, Any] = load_yaml_file(config_path)
        paths = config.get("paths")
        if paths:
            return paths
    except Exception:
        logger.debug(
            "Could not load component config paths for %s", component_id, exc_info=True
        )
    return None


def load_component_paths(
    project_root: Path,
    component_id: str,
    defaults: dict[str, str],
) -> dict[str, str]:
    """Return the component's declared path map, falling back to ``defaults``."""
    paths = _implementation_paths(project_root, component_id)
    if paths is None:
        paths = _component_config_paths(project_root, component_id)
    if paths is None:
        return dict(defaults)
    return paths


def resolve_component_path(
    project_root: Path,
    component_id: str,
    key: str,
    defaults: dict[str, str],
) -> Path:
    """Resolve a named component path relative to ``project_root``.

    Raises ``VAL-PATHS-001`` when the key is undefined after all fallbacks.
    """
    paths = load_component_paths(project_root, component_id, defaults)
    value = paths.get(key) or defaults.get(key, "")
    if not value:
        raise make_error(
            prefix="VAL",
            component="PATHS",
            number=1,
            kind="paths",
            message=f"path key {key!r} not defined for component {component_id!r}",
            details={"component": component_id, "key": key},
        )
    return project_root / value
