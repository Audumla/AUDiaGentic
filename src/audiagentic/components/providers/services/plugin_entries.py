"""Generic descriptor-backed plugin-entry management.

Routes all mutations through sync_managed_config (MA20): the service no longer
calls spec.writer/remover directly — ownership is tracked in a separate registry
file via the foundation ManagedFragmentRegistry and the shared reconciliation
engine preserves foreign plugin entries.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.contracts.plugin_entry import (
    PluginEntryMode,
    PluginEntryRequest,
    PluginEntryResult,
)
from audiagentic.foundation.toolchains.managed_config import (
    ManagedFragmentRegistry,
    resolve_managed_config_path,
    sync_managed_config,
)

from ..descriptors.registry import get_descriptor


def _plugin_ownership_registry(project_root: Path) -> ManagedFragmentRegistry:
    return ManagedFragmentRegistry(
        project_root,
        "managed-plugin-entries.json",
        top_level_key="providers",
    )


def manage_plugin_entry(
    project_root: Path,
    provider_id: str,
    *,
    mode: PluginEntryMode,
    request: PluginEntryRequest,
) -> PluginEntryResult:
    descriptor = get_descriptor(provider_id)
    spec = descriptor.plugin_config if descriptor else None
    if spec is None or not descriptor.automation_capability("plugin-entry"):
        return PluginEntryResult(False, False, error_code="RES-PPLG-001")
    if mode not in {"apply", "prune", "status"}:
        return PluginEntryResult(False, True, error_code="CON-PPLG-002")

    config_path = resolve_managed_config_path(spec, project_root)
    registry = _plugin_ownership_registry(project_root)
    options = request.options_mapping()
    entry_id = request.entry_id
    managed_id = entry_id  # stable id for registry tracking

    if mode == "status":
        current = spec.reader(config_path)
        actual = current.get(entry_id)
        return PluginEntryResult(
            ok=True,
            supported=True,
            provider_id=provider_id,
            present=actual is not None,
            changed=False,
        )

    # Build desired entries dict: {name: (managed_id, value)}
    if mode == "prune":
        desired_entries = {}
    else:  # apply
        desired_entries = {entry_id: (managed_id, options)}

    result = sync_managed_config(
        spec,
        project_root,
        request.ownership_scope,
        desired_entries,
        registry=registry,
    )

    changed = bool(result.updated) or bool(result.removed)
    return PluginEntryResult(
        ok=True,
        supported=True,
        provider_id=provider_id,
        changed=changed,
        present=bool(result.updated) or entry_id not in result.removed,
    )


__all__ = ["manage_plugin_entry"]
