"""MCP config propagation for component lifecycle events.

Extracted from components.py — handles harness refresh and publishes generic
MCP reconciliation events.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def _refresh_mcp_config_if_needed(descriptor, project_root: Path, *, reason: str) -> None:
    """Refresh harness MCP config when a component declares MCP servers."""
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
        logger.warning("Failed to refresh harness config for %s", descriptor.component_id, exc_info=True, extra={"component": descriptor.component_id})


def sync_all_provider_mcp_servers(project_root: Path) -> None:
    """Reconcile provider MCP config for all installed+enabled components.

    Safe to call at any time after component registration.
    """
    from audiagentic.components.providers.services.mcp_projection import (
        sync_component_mcp_to_providers,
    )
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import all_descriptors, is_enabled, is_installed

    register_all_components()
    for component_id, descriptor in all_descriptors().items():
        if not descriptor.mcp_servers and not descriptor.external_mcp_servers:
            continue
        if not descriptor.core and (not is_installed(component_id, project_root) or not is_enabled(component_id, project_root)):
            continue
        try:
            sync_component_mcp_to_providers(component_id, project_root)
        except Exception:
            logger.warning("Failed to sync MCP servers for %s", component_id, exc_info=True, extra={"component": component_id})
