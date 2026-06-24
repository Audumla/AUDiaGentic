from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.home import audiagentic_home
from audiagentic.foundation.paths.resolution import load_layered_mapping

_config_error = make_error_factory("CFG", "CONF", "config")


def load_layered_config(
    *,
    pkg_default_path: Path,
    project_root: Path | None = None,
    namespace: str,
) -> dict[str, Any]:
    """Load config from package default, user-global, and project-local tiers."""
    if not pkg_default_path.exists():
        raise _config_error(
            1,
            f"Package config missing (reinstall may be needed): {pkg_default_path}",
            path=str(pkg_default_path),
        )

    user_global_path = audiagentic_home() / "config" / f"{namespace}.yaml"
    project_local_path: Path | None = None
    if project_root is not None:
        project_local_path = (
            project_root / ".audiagentic" / "config" / f"{namespace}.yaml"
        )

    return load_layered_mapping(
        package_default_path=pkg_default_path,
        user_global_path=user_global_path,
        project_local_path=project_local_path,
    )
