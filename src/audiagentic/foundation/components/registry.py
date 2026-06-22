from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.foundation.home import audiagentic_home
from audiagentic.foundation.io import load_yaml_file

from .base import SCOPE_HARNESS, ComponentDescriptor, McpServerDeclaration

logger = logging.getLogger(__name__)

_registry: dict[str, ComponentDescriptor] = {}
_aliases: dict[str, str] = {}


def register(descriptor: ComponentDescriptor) -> None:
    for alias, owner in list(_aliases.items()):
        if owner == descriptor.component_id:
            del _aliases[alias]
    _registry[descriptor.component_id] = descriptor
    for alias in descriptor.aliases:
        _aliases[alias] = descriptor.component_id


def resolve_component_id(component_id: str) -> str | None:
    if component_id in _registry:
        return component_id
    return _aliases.get(component_id)


def get_descriptor(component_id: str) -> ComponentDescriptor | None:
    resolved = resolve_component_id(component_id) or component_id
    return _registry.get(resolved)


def all_descriptors() -> dict[str, ComponentDescriptor]:
    return dict(_registry)


def get_mcp_server_declaration(
    component_id: str,
    server_name: str,
) -> McpServerDeclaration | None:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return None
    for server in descriptor.mcp_servers:
        if server.name == server_name:
            return server
    return None


def component_root(descriptor: ComponentDescriptor, project_root: Path) -> Path:
    """Return the base directory for a component's files.

    Harness-scoped components resolve to audiagentic_home() so they are shared
    across all projects and are not tied to any single repo.
    """
    if descriptor.scope == SCOPE_HARNESS:
        return audiagentic_home()
    return project_root


def marker_path(component_id: str, root: Path, scope: str) -> Path:
    """Return the path to a component's installation marker file.

    Project scope:  root/.audiagentic/components/{id}.yaml
    Harness scope:  root/components/{id}.yaml  (root IS audiagentic_home())
    """
    if scope == SCOPE_HARNESS:
        return root / "components" / f"{component_id}.yaml"
    return root / ".audiagentic" / "components" / f"{component_id}.yaml"


def is_installed(component_id: str, project_root: Path) -> bool:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return False
    root = component_root(descriptor, project_root)
    return (root / descriptor.detection_marker).exists()


def is_enabled(component_id: str, project_root: Path) -> bool:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return False
    root = component_root(descriptor, project_root)
    mpath = marker_path(descriptor.component_id, root, descriptor.scope)
    if not mpath.exists():
        return False
    try:
        data = load_yaml_file(mpath)
    except Exception:
        logger.warning("Failed to read marker for %s", component_id, exc_info=True)
        return False
    return bool(data.get("enabled", True))


def get_external_probe_results(component_id: str, project_root: Path) -> dict[str, bool]:
    """Return cached external MCP server probe results stored in the component marker.

    Keys are server names; values are True (probe passed) or False (probe failed).
    Returns empty dict when no probes have been cached (e.g. older installs).
    """
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return {}
    root = component_root(descriptor, project_root)
    mpath = marker_path(component_id, root, descriptor.scope)
    if not mpath.exists():
        return {}
    try:
        data = load_yaml_file(mpath)
    except Exception:
        logger.warning("Failed to read marker for %s", component_id, exc_info=True)
        return {}
    return dict(data.get("external-mcp-probe", {}))
