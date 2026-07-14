from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.foundation.features.base import ImplementationDescriptor
from audiagentic.foundation.features.registry import register as register_feature_descriptor
from audiagentic.foundation.registry_utils import Registry

from ..services.host_capabilities import host_extension_statuses
from .base import ProviderDescriptor
from .feature_mapping import impl_features_for

_COMPONENT_ID = "providers"


def _load_providers() -> None:
    """(Re)load provider descriptors from YAML into this registry.

    Importing the adapters package registers all providers as a side effect;
    the explicit call covers re-population after reset_all_registries().
    """
    from audiagentic.components.providers import adapters

    adapters.load_providers()


_registry: Registry[ProviderDescriptor] = Registry(loader=_load_providers)


def _register_feature_implementation(descriptor: ProviderDescriptor) -> None:
    register_feature_descriptor(
        ImplementationDescriptor(
            parent=_COMPONENT_ID,
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
    # replace=True: descriptors are rebuilt as new instances on every YAML
    # (re)load, so strict same-value idempotency would reject legitimate reloads.
    _registry.register(descriptor.provider_id, descriptor, replace=True)
    _register_feature_implementation(descriptor)


def get_descriptor(provider_id: str) -> ProviderDescriptor | None:
    _sync_feature_implementations()
    return _registry.get(provider_id)


def all_descriptors() -> dict[str, ProviderDescriptor]:
    _sync_feature_implementations()
    return _registry.all()


def canonical_provider_ids() -> tuple[str, ...]:
    """Return all registered provider ids. Owned by the providers component."""
    return _registry.keys()


def provider_alias_map() -> dict[str, str]:
    """Return prompt/provider aliases contributed by provider descriptors.

    Maps each canonical id and each prompt alias to the canonical id.
    """
    aliases: dict[str, str] = {}
    for provider_id, descriptor in _registry.all().items():
        aliases[provider_id] = provider_id
        for alias in descriptor.prompt_aliases or ():
            aliases[alias] = provider_id
    return aliases


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

    hosts, host_capabilities = host_extension_statuses(
        project_root,
        descriptor.host_capabilities,
    )

    cli_probe = descriptor.cli_probe
    if descriptor.cli_install and descriptor.cli_install.package_manager == "vscode":
        cli_probe = None

    result: dict[str, Any] = {
        "provider_id": provider_id,
        "display_name": descriptor.display_name,
        "registered": True,
        "deprecated": descriptor.deprecated,
        "annotations": dict(descriptor.annotations) if descriptor.annotations else None,
        "cli": _probe_cli(cli_probe) if cli_probe else None,
        "host_capabilities": host_capabilities,
        "hosts": {host_id: {"workspace": workspace} for host_id, workspace in hosts.items()},
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
