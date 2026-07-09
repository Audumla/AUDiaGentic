from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.home import audiagentic_home
from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME
from audiagentic.foundation.registry_utils import Registry

from .base import SCOPE_HARNESS, ComponentDescriptor, McpServerDeclaration

logger = logging.getLogger(__name__)

_registry = Registry[ComponentDescriptor](aliases=True)
_LOADING_DEFAULT_COMPONENTS = False


def _set_default_loading(value: bool) -> None:
    global _LOADING_DEFAULT_COMPONENTS
    _LOADING_DEFAULT_COMPONENTS = value


def _self_populate() -> None:
    if _LOADING_DEFAULT_COMPONENTS or _registry.keys():
        return
    from audiagentic.foundation.components.loader import register_all_components

    register_all_components()


def register(descriptor: ComponentDescriptor, *, replace: bool = False) -> None:
    """Register a component descriptor.

    By default, re-registering the same descriptor object is idempotent, and
    registering a *different* descriptor under an existing key raises (collision
    detection gained from CP10 Registry adoption).  Pass ``replace=True`` for
    the loader's cross-layer overwrite path (CP04: profile wins over base).
    """
    if replace:
        _registry.pop(descriptor.component_id)
    _registry.register(
        descriptor.component_id,
        descriptor,
        aliases=list(descriptor.aliases),
    )


def resolve_component_id(component_id: str) -> str | None:
    _self_populate()
    return _registry.resolve(component_id)


def get_descriptor(component_id: str) -> ComponentDescriptor | None:
    _self_populate()
    resolved = resolve_component_id(component_id) or component_id
    return _registry.get(resolved)


def all_descriptors() -> dict[str, ComponentDescriptor]:
    _self_populate()
    return _registry.all()


def reset() -> None:
    """Clear the component registry. Used for test isolation.

    Clears internal storage and invalidates the loader's registration
    cache guard so that a subsequent lazy register_all_components() call
    re-populates all registries instead of returning stale cache data.
    """
    _registry.reset()
    from audiagentic.foundation.components.loader import (
        _reset_registration_cache,
    )

    _reset_registration_cache()


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
    return root / PROJECT_MARKER_NAME / "components" / f"{component_id}.yaml"


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
