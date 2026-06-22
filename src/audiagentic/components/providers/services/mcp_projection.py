from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.registry import get_descriptor
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.launch import component_mcp_launch

from ..descriptors.registry import all_descriptors
from .feature_resolution import resolve_active_provider_features
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

    active_mcp_providers = {
        resolved.provider_id
        for resolved in resolve_active_provider_features(project_root)
        if resolved.kind == "mcp"
    }

    providers = all_descriptors()
    for provider_id, pdesc in providers.items():
        if pdesc.mcp_config is None:
            continue
        provider_active = enabled and provider_id in active_mcp_providers
        if not pdesc.receive_lsp_mcp:
            continue
        desired_entries: dict[str, tuple[str, McpServerEntry]] = {}
        managed_ids: set[str] = set()
        for mcp_def in descriptor.mcp_servers or ():
            managed_id = mcp_def.managed_id or mcp_def.name
            managed_ids.add(managed_id)
            if "providers" in mcp_def.propagate and provider_active:
                command, args, env = component_mcp_launch(
                    mcp_def.module, extra_args=tuple(mcp_def.args)
                )
                desired_entries[managed_id] = (
                    mcp_def.name,
                    McpServerEntry(
                        name=mcp_def.name,
                        command=command,
                        args=args,
                        env=env,
                    ),
                )
        for mcp_def in descriptor.external_mcp_servers or ():
            managed_id = mcp_def.managed_id or mcp_def.name
            managed_ids.add(managed_id)
            if "providers" in mcp_def.propagate and provider_active:
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
