"""MCP server synchronization for provider reconciliation.

Moved from foundation/lifecycle/component_mcp.py — this is providers-domain
logic that belongs in the owning component. Called directly by reconcile.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def sync_all_provider_mcp_servers(project_root: Path) -> list[dict[str, str]]:
    """Reconcile provider MCP config for all installed components.

    Installed+enabled components project their MCP entries; installed-but-disabled
    components are synced with an empty desired set so their entries get pruned
    (disable revokes tool access, matching uninstall — only install-time management
    state differs between the two).
    """
    from audiagentic.foundation.components.registry import (
        all_descriptors,
        is_enabled,
        is_installed,
    )

    from .mcp_projection import sync_component_mcp_to_providers

    errors: list[dict[str, str]] = []
    for component_id, descriptor in all_descriptors().items():
        if not descriptor.mcp_servers and not descriptor.external_mcp_servers:
            continue
        if not descriptor.core and not is_installed(component_id, project_root):
            continue
        active = descriptor.core or is_enabled(component_id, project_root)
        try:
            sync_component_mcp_to_providers(component_id, project_root, enabled=active)
        except Exception as exc:
            logger.warning(
                "Failed to sync MCP servers for %s",
                component_id,
                exc_info=True,
                extra={"component": component_id},
            )
            errors.append({"component": component_id, "error": str(exc)})
    return errors
