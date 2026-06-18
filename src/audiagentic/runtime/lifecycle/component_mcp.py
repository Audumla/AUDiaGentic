"""MCP config propagation for component lifecycle events.

Extracted from components.py — handles refresh, per-provider propagation,
and full reconciliation of MCP servers.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _refresh_mcp_config_if_needed(descriptor, project_root: Path, *, reason: str) -> None:
    """Refresh harness MCP config and propagate to providers if component declares MCP servers."""
    if not descriptor.mcp_servers and not descriptor.external_mcp_servers:
        return
    try:
        from audiagentic.runtime.harness import refresh_harness_config_if_installed
        refresh_harness_config_if_installed(
            project_root,
            reason=reason,
            component_id=descriptor.component_id,
        )
    except Exception:
        logger.warning("Failed to refresh harness config for %s", descriptor.component_id, exc_info=True)
    try:
        _propagate_mcp_to_providers(
            descriptor,
            project_root,
            enabled=reason != "component-uninstalled",
        )
    except Exception:
        logger.warning("Failed to propagate MCP config for %s", descriptor.component_id, exc_info=True)


def _propagate_mcp_to_providers(descriptor, project_root: Path, *, enabled: bool = True) -> None:
    """Add/remove component MCP servers on every provider that has mcp_config defined.

    Servers with propagate containing "providers" are added.
    Servers with propagate not containing "providers" are pruned (removes stale entries).
    """
    importlib.import_module("audiagentic.components.optional.providers")
    from audiagentic.components.optional.providers.descriptors.registry import all_descriptors
    from audiagentic.components.optional.providers.services.mcp import (
        sync_managed_provider_mcp_subset,
    )
    from audiagentic.runtime.harness.paths import find_package_root

    python = sys.executable.replace("\\", "/")
    src_dir = str(find_package_root(Path(__file__)).parent).replace("\\", "/")

    providers = all_descriptors()
    for provider_id, pdesc in providers.items():
        if pdesc.mcp_config is None:
            continue
        desired_entries: dict[str, tuple[str, object]] = {}
        managed_ids: set[str] = set()
        for mcp_def in (descriptor.mcp_servers or []):
            managed_id = mcp_def.managed_id or mcp_def.name
            managed_ids.add(managed_id)
            if "providers" in mcp_def.propagate:
                from audiagentic.foundation.mcp import McpServerEntry

                if enabled:
                    desired_entries[managed_id] = (
                        mcp_def.name,
                        McpServerEntry(
                            name=mcp_def.name,
                            command=python,
                            args=("-m", mcp_def.module) + tuple(mcp_def.args),
                            env={"PYTHONPATH": src_dir},
                        ),
                    )
        for mcp_def in (descriptor.external_mcp_servers or []):
            managed_id = mcp_def.managed_id or mcp_def.name
            managed_ids.add(managed_id)
            if "providers" in mcp_def.propagate:
                from audiagentic.foundation.mcp import McpServerEntry

                if enabled:
                    desired_entries[managed_id] = (
                        mcp_def.name,
                        McpServerEntry(
                            name=mcp_def.name,
                            command=mcp_def.command,
                            args=tuple(mcp_def.args),
                            env=dict(mcp_def.env) if mcp_def.env else {},
                        ),
                    )
        sync_managed_provider_mcp_subset(
            provider_id=provider_id,
            project_root=project_root,
            desired_entries=desired_entries,
            managed_ids=managed_ids,
        )


def sync_all_provider_mcp_servers(project_root: Path) -> None:
    """Reconcile MCP servers across all provider configs for all installed+enabled components.

    Adds servers with propagate containing "providers" and removes servers that
    are known but not meant for providers. Safe to call at any time — converges
    to the correct state regardless of prior history.
    """
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import all_descriptors, is_enabled, is_installed

    register_all_components()
    for component_id, descriptor in all_descriptors().items():
        if not descriptor.mcp_servers and not descriptor.external_mcp_servers:
            continue
        if not descriptor.core and not is_installed(component_id, project_root):
            continue
        if not descriptor.core and not is_enabled(component_id, project_root):
            continue
        try:
            _propagate_mcp_to_providers(descriptor, project_root)
        except Exception:
            logger.warning("Failed to sync MCP servers for %s", component_id, exc_info=True)
