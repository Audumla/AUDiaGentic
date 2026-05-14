from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from audiagentic.provisioning.home import audiagentic_home


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with overlay merged on top of base, recursing into nested dicts."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file; return {} if the file does not exist."""
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_layered_config(
    *,
    pkg_default_path: Path,
    project_root: Path | None = None,
    namespace: str,
) -> dict[str, Any]:
    """Load config from three tiers and deep-merge them.

    Tiers (lowest to highest priority):
      1. pkg_default_path  — package-shipped defaults; must exist.
      2. $AUDIAGENTIC_HOME/config/<namespace>.yaml  — user-global overrides.
      3. <project_root>/.audiagentic/config/<namespace>.yaml  — project-local overrides.

    If the project-local file contains ``exclusive_local: true`` the user-global
    tier is skipped entirely.  The key is stripped before the merged dict is returned.

    Args:
        pkg_default_path: Absolute path to the package default YAML (must exist).
        project_root: Project root directory; if None, the project-local tier is skipped.
        namespace: Slash-separated namespace string, e.g. ``"harness/ag"``.
                   Maps to ``config/<namespace>.yaml`` in both global and local dirs.
    """
    if not pkg_default_path.exists():
        raise SystemExit(
            f"Package config missing (reinstall may be needed): {pkg_default_path}"
        )

    user_global_path = audiagentic_home() / "config" / f"{namespace}.yaml"
    project_local_path: Path | None = None
    if project_root is not None:
        project_local_path = (
            project_root / ".audiagentic" / "config" / f"{namespace}.yaml"
        )

    defaults = _load_yaml(pkg_default_path)

    local: dict[str, Any] = {}
    if project_local_path is not None:
        local = _load_yaml(project_local_path)

    exclusive_local = bool(local.pop("exclusive_local", False))

    user_global: dict[str, Any] = {} if exclusive_local else _load_yaml(user_global_path)

    result = _deep_merge(defaults, user_global)
    result = _deep_merge(result, local)
    return result
