from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.registry import get_descriptor
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.component_builder import (
    entry_from_external_declaration,
    entry_from_mcp_declaration,
)

from ..descriptors.registry import all_descriptors
from .mcp import sync_managed_provider_mcp_subset


def sync_component_mcp_to_providers(
    component_id: str,
    project_root: Path,
    *,
    enabled: bool = True,
) -> None:
    """Project one component's provider-propagated MCP declarations to providers."""
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return
    if not descriptor.mcp_servers and not descriptor.external_mcp_servers:
        return

    providers = all_descriptors()
    for provider_id, pdesc in providers.items():
        if pdesc.mcp_config is None:
            continue
        # Project to every MCP-capable provider regardless of whether its CLI is
        # currently active/installed — inactive providers stay configured and
        # ready, so switching to them never leaves stale or missing MCP entries.
        desired_entries: dict[str, tuple[str, McpServerEntry]] = {}
        managed_ids: set[str] = set()
        for mcp_def in descriptor.mcp_servers or ():
            managed_id = mcp_def.managed_id or mcp_def.name
            managed_ids.add(managed_id)
            if "providers" in mcp_def.propagate and enabled:
                desired_entries[managed_id] = (mcp_def.name, entry_from_mcp_declaration(mcp_def))
        for mcp_def in descriptor.external_mcp_servers or ():
            managed_id = mcp_def.managed_id or mcp_def.name
            managed_ids.add(managed_id)
            if "providers" in mcp_def.propagate and enabled:
                desired_entries[managed_id] = (mcp_def.name, entry_from_external_declaration(mcp_def))
        sync_managed_provider_mcp_subset(
            provider_id=provider_id,
            project_root=project_root,
            desired_entries=desired_entries,
            managed_ids=managed_ids,
        )
