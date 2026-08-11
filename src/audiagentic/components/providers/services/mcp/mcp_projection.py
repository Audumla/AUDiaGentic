from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.registry import get_descriptor
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.component_builder import (
    entry_from_external_declaration,
    entry_from_mcp_declaration,
)

from ...descriptors.registry import all_descriptors
from ..config.provider_config import is_provider_enabled
from .mcp import sync_managed_provider_mcp_subset
from .managed_mcp_registry import load_managed_mcp_registry


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

    managed_ids = {
        mcp_def.managed_id or mcp_def.name
        for mcp_def in (*descriptor.mcp_servers, *descriptor.external_mcp_servers)
        if "providers" in mcp_def.propagate
    }
    providers = all_descriptors()
    for provider_id, pdesc in providers.items():
        if pdesc.mcp_config is None:
            continue
        # Active projection is strictly limited to enabled providers.  Disabled
        # providers are not maintained; the enabled=False cleanup path below is
        # still allowed to visit every provider so old owned entries are pruned
        # when a component is disabled or uninstalled.
        if enabled and not is_provider_enabled(project_root, provider_id):
            # A provider that is already disabled must not be maintained.  If
            # it owns stale entries from before the disable, prune only those
            # entries; do not write an empty config for an untouched provider.
            owned = load_managed_mcp_registry(project_root).get(provider_id, {})
            stale_ids = managed_ids & set(owned)
            if stale_ids:
                sync_managed_provider_mcp_subset(
                    provider_id=provider_id,
                    project_root=project_root,
                    desired_entries={},
                    managed_ids=stale_ids,
                )
            continue
        desired_entries: dict[str, tuple[str, McpServerEntry]] = {}
        for mcp_def in descriptor.mcp_servers or ():
            managed_id = mcp_def.managed_id or mcp_def.name
            if "providers" in mcp_def.propagate and enabled:
                desired_entries[managed_id] = (
                    mcp_def.name,
                    entry_from_mcp_declaration(mcp_def, project_root),
                )
        for mcp_def in descriptor.external_mcp_servers or ():
            managed_id = mcp_def.managed_id or mcp_def.name
            if "providers" in mcp_def.propagate and enabled:
                desired_entries[managed_id] = (mcp_def.name, entry_from_external_declaration(mcp_def))
        sync_managed_provider_mcp_subset(
            provider_id=provider_id,
            project_root=project_root,
            desired_entries=desired_entries,
            managed_ids=managed_ids,
        )
