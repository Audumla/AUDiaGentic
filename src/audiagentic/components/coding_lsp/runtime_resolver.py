from __future__ import annotations

from pathlib import Path

from audiagentic.components.coding_lsp import language_registry
from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig
from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
from audiagentic.foundation.features.base import BindingDescriptor
from audiagentic.foundation.features.registry import get_bindings, get_implementations
from audiagentic.foundation.features.state import (
    get_component_state,
    get_feature_state,
)

# Ultimate fallback only — used if no implementation descriptors are registered.
_FALLBACK_IMPLEMENTATION_ID = "ag-lsp"


def default_lsp_implementation() -> str:
    """Default active implementation, sourced from descriptor metadata.

    An implementation descriptor marks itself with ``default: true``; if none does,
    the first registered implementation (sorted) is used. Falls back to a constant
    only when no implementations are registered at all.
    """
    implementations = get_implementations(COMPONENT_CODING_LSP)
    for implementation_id in sorted(implementations):
        if implementations[implementation_id].raw.get("default") is True:
            return implementation_id
    return next(iter(sorted(implementations)), _FALLBACK_IMPLEMENTATION_ID)


def active_lsp_implementation(project_root: Path) -> str:
    """Return the enabled LSP implementation, or the descriptor-defined default."""
    component = get_component_state(project_root, COMPONENT_CODING_LSP)
    implementations = component.get("implementations") or {}
    if isinstance(implementations, dict):
        for implementation_id, state in implementations.items():
            if isinstance(implementation_id, str) and isinstance(state, dict) and state.get("enabled"):
                return implementation_id
    return default_lsp_implementation()


def active_language_bindings(project_root: Path) -> list[BindingDescriptor]:
    active_implementation = active_lsp_implementation(project_root)
    bindings: list[BindingDescriptor] = []
    for (implementation, feature_kind, feature), binding in get_bindings(COMPONENT_CODING_LSP).items():
        if implementation != active_implementation or feature_kind != "language":
            continue
        state = get_feature_state(project_root, COMPONENT_CODING_LSP, "language", feature)
        if state.enabled:
            bindings.append(binding)
    return bindings


def resolve_active_runtime_servers(project_root: Path) -> dict[str, ServerConfig]:
    servers: dict[str, ServerConfig] = {}
    for binding in active_language_bindings(project_root):
        language = binding.feature
        if language in servers:
            continue
        spec = language_registry.get_language(language)
        if spec is None:
            continue
        state = get_feature_state(project_root, COMPONENT_CODING_LSP, "language", language)
        server_settings = state.options.get("server-settings", {})
        if not isinstance(server_settings, dict):
            server_settings = {}
        servers[language] = ServerConfig(
            command=list(spec.command),
            file_extensions=list(spec.file_extensions),
            workspace_config_files=list(spec.workspace_config_files),
            settings={**dict(spec.settings), **server_settings},
            label=spec.display_name,
        )
    return servers
