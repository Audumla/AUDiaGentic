"""Generic descriptor-backed plugin-entry management."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.contracts.plugin_entry import (
    PluginEntryMode,
    PluginEntryRequest,
    PluginEntryResult,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor


def manage_plugin_entry(
    project_root: Path,
    provider_id: str,
    *,
    mode: PluginEntryMode,
    request: PluginEntryRequest,
) -> PluginEntryResult:
    descriptor = get_descriptor(provider_id)
    spec = descriptor.plugin_config if descriptor else None
    if spec is None:
        return PluginEntryResult(False, False, error_code="RES-PPLG-001")
    if mode not in {"apply", "prune", "status"}:
        return PluginEntryResult(False, True, error_code="CON-PPLG-002")
    path = spec.config_path(project_root) if callable(spec.config_path) else Path(spec.config_path)
    path = Path(path)
    if not path.is_absolute():
        path = project_root / path
    current = spec.reader(path, request.entry_id)
    if mode == "status":
        return PluginEntryResult(True, True, present=current == request.options_mapping())
    if mode == "prune":
        changed = spec.remover(path, request.entry_id)
        return PluginEntryResult(True, True, changed=changed, present=False)
    expected = request.options_mapping()
    if current == expected:
        return PluginEntryResult(True, True, present=True)
    spec.writer(path, request.entry_id, expected)
    return PluginEntryResult(True, True, changed=True, present=True)


__all__ = ["manage_plugin_entry"]
