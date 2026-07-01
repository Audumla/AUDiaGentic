from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.descriptors.registry import DescriptorRegistry
from audiagentic.foundation.features.base import ImplementationDescriptor
from audiagentic.foundation.features.registry import register as register_feature_descriptor

from ..services.host_capabilities import vscode_extension_statuses
from .base import ProviderDescriptor
from .feature_mapping import impl_features_for

_registry: DescriptorRegistry[ProviderDescriptor] = DescriptorRegistry()


def _register_feature_implementation(descriptor: ProviderDescriptor) -> None:
    register_feature_descriptor(
        ImplementationDescriptor(
            parent=COMPONENT_PROVIDERS,
            implementation_id=descriptor.provider_id,
            display_name=descriptor.display_name,
            description=descriptor.description,
            raw={"provider-descriptor": descriptor.provider_id},
        )
    )
    # Capability -> impl-scoped feature mapping is owned by feature_mapping; this
    # registry only registers what that module derives (idempotent re-registration).
    for feature in impl_features_for(descriptor):
        register_feature_descriptor(feature)


def _sync_feature_implementations() -> None:
    for descriptor in _registry.all().values():
        _register_feature_implementation(descriptor)


def register(descriptor: ProviderDescriptor) -> None:
    _registry.register(descriptor.provider_id, descriptor)
    _register_feature_implementation(descriptor)


def get_descriptor(provider_id: str) -> ProviderDescriptor | None:
    _sync_feature_implementations()
    return _registry.get(provider_id)


def all_descriptors() -> dict[str, ProviderDescriptor]:
    _sync_feature_implementations()
    return _registry.all()


def canonical_provider_ids() -> tuple[str, ...]:
    """Return all registered provider ids. Owned by the providers component."""
    return _registry.ids()


def provider_alias_map() -> dict[str, str]:
    """Return prompt/provider aliases contributed by provider descriptors."""
    return _registry.alias_map(aliases_field="prompt_aliases")


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
    resolved_command = [executable] + list(command[1:])
    try:
        completed = subprocess.run(
            resolved_command,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
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


def interrogate(provider_id: str, project_root: Path) -> dict[str, Any]:
    """Return full interrogation result for a provider against a project root."""
    descriptor = _registry.get(provider_id)
    if descriptor is None:
        return {"provider_id": provider_id, "registered": False}

    is_vscode_project, vscode_extensions = vscode_extension_statuses(
        project_root,
        descriptor.vscode_extensions,
    )
    host_capabilities = list(vscode_extensions)

    cli_probe = descriptor.cli_probe
    if descriptor.cli_install and descriptor.cli_install.package_manager == "vscode":
        cli_probe = None

    result: dict[str, Any] = {
        "provider_id": provider_id,
        "display_name": descriptor.display_name,
        "registered": True,
        "cli": _probe_cli(cli_probe) if cli_probe else None,
        "host_capabilities": host_capabilities,
        "vscode_project": is_vscode_project,
        "vscode_extensions": vscode_extensions,
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
