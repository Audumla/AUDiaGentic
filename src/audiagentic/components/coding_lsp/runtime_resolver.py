from __future__ import annotations

from pathlib import Path

from audiagentic.components.coding_lsp import language_registry
from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig
from audiagentic.foundation.features.base import BindingDescriptor
from audiagentic.foundation.features.registry import get_bindings, get_implementations
from audiagentic.foundation.features.state import (
    get_component_state,
    get_feature_state,
)

_COMPONENT_ID = "coding-lsp"

# Ultimate fallback only — used if no implementation descriptors are registered.
_FALLBACK_IMPLEMENTATION_ID = "ag-lsp"


def default_lsp_implementation() -> str:
    """Default active implementation, sourced from descriptor metadata.

    An implementation descriptor marks itself with ``default: true``; if none does,
    the first registered implementation (sorted) is used. Falls back to a constant
    only when no implementations are registered at all.
    """
    implementations = get_implementations(_COMPONENT_ID)
    for implementation_id in sorted(implementations):
        if implementations[implementation_id].raw.get("default") is True:
            return implementation_id
    return next(iter(sorted(implementations)), _FALLBACK_IMPLEMENTATION_ID)


def active_lsp_implementation(project_root: Path) -> str:
    """Return the enabled LSP implementation, or the descriptor-defined default."""
    component = get_component_state(project_root, _COMPONENT_ID)
    implementations = component.get("implementations") or {}
    if isinstance(implementations, dict):
        for implementation_id, state in implementations.items():
            if isinstance(implementation_id, str) and isinstance(state, dict) and state.get("enabled"):
                return implementation_id
    return default_lsp_implementation()


def active_language_bindings(project_root: Path) -> list[BindingDescriptor]:
    active_implementation = active_lsp_implementation(project_root)
    bindings: list[BindingDescriptor] = []
    for (implementation, feature_kind, feature), binding in get_bindings(_COMPONENT_ID).items():
        if implementation != active_implementation or feature_kind != "language":
            continue
        state = get_feature_state(project_root, _COMPONENT_ID, "language", feature)
        if state.enabled:
            bindings.append(binding)
    return bindings


def resolve_active_runtime_servers(project_root: Path) -> dict[str, list[ServerConfig]]:
    """Return all active server configs per language, ordered (semantic server first).

    Returns dict[language → list[ServerConfig]] where each ServerConfig has
    server_id set to the dependency id from the language YAML. Multiple entries
    per language are possible when >1 server feature is active for that language.
    """
    servers: dict[str, list[ServerConfig]] = {}
    for binding in active_language_bindings(project_root):
        language = binding.feature
        spec = language_registry.get_language(language)
        if spec is None:
            continue
        state = get_feature_state(project_root, _COMPONENT_ID, "language", language)
        server_settings = state.options.get("server-settings", {})
        if not isinstance(server_settings, dict):
            server_settings = {}
        dep_id = spec.dependency.id if spec.dependency is not None else spec.id
        cfg = ServerConfig(
            command=list(spec.command),
            file_extensions=list(spec.file_extensions),
            workspace_config_files=list(spec.workspace_config_files),
            settings={**dict(spec.settings), **server_settings},
            label=spec.display_name,
            server_id=dep_id,
            init_wait=spec.init_wait,
        )
        existing_ids = {s.server_id for s in servers.get(language, [])}
        if dep_id not in existing_ids:
            servers.setdefault(language, []).append(cfg)
    return servers
