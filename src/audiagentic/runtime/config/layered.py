from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from audiagentic.runtime.config.files import load_yaml_file
from audiagentic.runtime.home import audiagentic_home


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return new dict with overlay merged on top of base."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_layered_config(
    *,
    pkg_default_path: Path,
    project_root: Path | None = None,
    namespace: str,
) -> dict[str, Any]:
    """Load config from package default, user-global, and project-local tiers."""
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

    defaults = load_yaml_file(pkg_default_path)
    local = load_yaml_file(project_local_path) if project_local_path is not None else {}
    exclusive_local = bool(local.pop("exclusive_local", False))
    user_global = {} if exclusive_local else load_yaml_file(user_global_path)

    result = _deep_merge(defaults, user_global)
    return _deep_merge(result, local)
