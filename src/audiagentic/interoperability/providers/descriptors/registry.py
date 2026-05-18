from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import ProviderDescriptor, VsCodeExtension

_registry: dict[str, ProviderDescriptor] = {}
_vscode_ext_cache: list[str] | None = None
_vscode_ext_probed: bool = False


def register(descriptor: ProviderDescriptor) -> None:
    _registry[descriptor.provider_id] = descriptor


def get_descriptor(provider_id: str) -> ProviderDescriptor | None:
    return _registry.get(provider_id)


def all_descriptors() -> dict[str, ProviderDescriptor]:
    return dict(_registry)


def _probe_cli(command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if executable is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    try:
        completed = subprocess.run(
            subprocess.list2cmdline(command),
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "command": command,
            "executable": executable,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "available": completed.returncode == 0,
        "command": command,
        "executable": executable,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _list_vscode_extensions(*, allow_probe: bool = True) -> list[str] | None:
    """Return installed VS Code extension IDs (lowercase) by reading ~/.vscode/extensions.

    Reads the extensions directory directly — no subprocess, no risk of opening VS Code.
    allow_probe=False returns the cache only (never reads disk). Pass False from launch
    or background contexts.
    """
    global _vscode_ext_cache, _vscode_ext_probed
    if _vscode_ext_probed:
        return _vscode_ext_cache
    if not allow_probe:
        return None
    _vscode_ext_probed = True
    import re
    ext_dir = Path.home() / ".vscode" / "extensions"
    if not ext_dir.exists():
        _vscode_ext_cache = None
        return None
    ids: list[str] = []
    try:
        for p in ext_dir.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            # Directory names: publisher.name-version or publisher.name-version-platform-arch
            # Extract just publisher.name by stopping at first hyphen-then-digit.
            m = re.match(r"^([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+?)(?:-\d+.*)?$", p.name)
            if m:
                ids.append(m.group(1).lower())
    except OSError:
        _vscode_ext_cache = None
        return None
    _vscode_ext_cache = ids
    return _vscode_ext_cache


def _probe_extension(ext: VsCodeExtension, *, is_vscode_project: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "extension_id": ext.extension_id,
        "display_name": ext.display_name,
        "applicable": is_vscode_project,
        "installed": False,
    }
    if not is_vscode_project:
        return entry
    installed_list = _list_vscode_extensions()
    if installed_list is None:
        entry["probe_error"] = "code CLI unavailable"
    else:
        entry["installed"] = ext.extension_id.lower() in installed_list
    return entry


def interrogate(provider_id: str, project_root: Path) -> dict[str, Any]:
    """Return full interrogation result for a provider against a project root."""
    descriptor = _registry.get(provider_id)
    if descriptor is None:
        return {"provider_id": provider_id, "registered": False}

    is_vscode_project = (project_root / ".vscode").exists()

    result: dict[str, Any] = {
        "provider_id": provider_id,
        "display_name": descriptor.display_name,
        "registered": True,
        "cli": _probe_cli(descriptor.cli_probe) if descriptor.cli_probe else None,
        "vscode_project": is_vscode_project,
        "vscode_extensions": [
            _probe_extension(ext, is_vscode_project=is_vscode_project)
            for ext in descriptor.vscode_extensions
        ],
        "permissions": {
            "can_write_files": descriptor.permissions.can_write_files,
            "can_execute_shell": descriptor.permissions.can_execute_shell,
            "can_browse_web": descriptor.permissions.can_browse_web,
            "can_read_env": descriptor.permissions.can_read_env,
            "notes": descriptor.permissions.notes,
        },
        "agent_files": [
            {
                "rel_path": af.rel_path,
                "managed": af.managed,
                "description": af.description,
                "exists": (project_root / af.rel_path).exists(),
            }
            for af in descriptor.agent_files
        ],
    }
    return result
