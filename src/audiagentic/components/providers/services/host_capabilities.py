from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, to_error_envelope

from ..descriptors.base import HostCapability

_vscode_ext_cache: list[str] | None = None
_vscode_ext_probed: bool = False


def list_vscode_extensions(*, allow_probe: bool = True) -> list[str] | None:
    """Return installed VS Code extension IDs without spawning VS Code."""
    global _vscode_ext_cache, _vscode_ext_probed
    if _vscode_ext_probed:
        return _vscode_ext_cache
    if not allow_probe:
        return None
    _vscode_ext_probed = True
    ext_dir = Path.home() / ".vscode" / "extensions"
    if not ext_dir.exists():
        _vscode_ext_cache = None
        return None
    ids: list[str] = []
    try:
        for path in ext_dir.iterdir():
            if not path.is_dir() or path.name.startswith("."):
                continue
            match = re.match(
                r"^([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+?)(?:-\d+.*)?$",
                path.name,
            )
            if match:
                ids.append(match.group(1).lower())
    except OSError:
        _vscode_ext_cache = None
        return None
    _vscode_ext_cache = ids
    return _vscode_ext_cache


def is_vscode_project(project_root: Path) -> bool:
    return (project_root / ".vscode").exists()


def vscode_extension_status(
    ext: HostCapability,
    *,
    is_project: bool,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "host": ext.host,
        "capability_id": ext.capability_id,
        "extension_id": ext.capability_id,
        "display_name": ext.display_name,
        "applicable": is_project,
        "installed": None,
    }
    if not is_project:
        return entry
    installed_list = list_vscode_extensions()
    if installed_list is None:
        entry["error"] = to_error_envelope(
            AudiaGenticError(
                code="CFG-PVEXT-001",
                kind="providers",
                message="VS Code extension state unavailable",
                details={
                    "extension-id": ext.capability_id,
                    "source": "vscode-extension-probe",
                    "path": str(Path.home() / ".vscode" / "extensions"),
                },
            )
        )
    else:
        entry["installed"] = ext.capability_id.lower() in installed_list
    return entry


def vscode_extension_statuses(
    project_root: Path,
    extensions: tuple[HostCapability, ...],
) -> tuple[bool, list[dict[str, Any]]]:
    project = is_vscode_project(project_root)
    return project, [
        vscode_extension_status(extension, is_project=project)
        for extension in extensions
    ]
