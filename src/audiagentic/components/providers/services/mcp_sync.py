"""MCP server synchronization for provider reconciliation.

Moved from foundation/lifecycle/component_mcp.py — this is providers-domain
logic that belongs in the owning component. Called directly by reconcile.py.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def sync_all_provider_mcp_servers(project_root: Path) -> None:
    """Reconcile provider MCP config for all installed+enabled components.

    Direct relocation from foundation/lifecycle/component_mcp.py — no capability
    indirection needed since this function now lives inside the providers component.
    """
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import (
        all_descriptors,
        is_enabled,
        is_installed,
    )

    from ..services.mcp_projection import sync_component_mcp_to_providers

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
