"""LSP recipe adapter — maps coding-lsp behavior to provider recipe model.

This module provides a thin adapter that expresses the existing LSP provider
native support in terms of the provider recipe model, without changing behavior.

Shared model:
- Capability component (coding-lsp) exports generic desired state (language specs)
- Provider layer selects native recipe or generic fallback
- Foundation toolchains own generic execution primitives (StepRecipe, probes)

Mapping:
- `language_servers_config` = config recipe (provider-owned MCP config writes)
- `on_lsp_enabled` = native provision recipe (provider-specific LSP setup)
- `receive_lsp_mcp` = generic MCP fallback policy (opt-out of ag-lsp projection)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeResult,
    RecipeState,
)


@dataclass(frozen=True)
class LspRecipeAdapter:
    """Adapter that maps LSP provider descriptor fields to recipe concepts.

    This is a metadata-only adapter — it does not execute LSP provisioning.
    It documents how the existing fields map to the provider recipe model.
    """

    provider_id: str
    display_name: str
    has_native_lsp: bool
    """True if provider has `on_lsp_enabled` (self-providing LSP)."""
    receives_ag_lsp_mcp: bool
    """True if provider receives the ag-lsp MCP server projection."""
    has_lsp_config: bool
    """True if provider has `language_servers_config` spec."""
    recipe_kind: ProviderRecipeKind
    """The dominant strategy kind for this provider's LSP support."""

    @classmethod
    def from_descriptor(cls, descriptor: Any) -> LspRecipeAdapter:
        """Build adapter from a ProviderDescriptor.

        The descriptor must have: provider_id, display_name, on_lsp_enabled,
        receive_lsp_mcp, language_servers_config.
        """
        has_native = descriptor.on_lsp_enabled is not None
        receives_mcp = descriptor.receive_lsp_mcp
        has_config = descriptor.language_servers_config is not None

        if has_native and has_config:
            kind = ProviderRecipeKind.HYBRID
        elif has_native:
            kind = ProviderRecipeKind.NATIVE_PASSTHROUGH
        elif has_config:
            kind = ProviderRecipeKind.MCP_CONFIG
        else:
            kind = ProviderRecipeKind.GUIDANCE_ONLY

        return cls(
            provider_id=descriptor.provider_id,
            display_name=descriptor.display_name,
            has_native_lsp=has_native,
            receives_ag_lsp_mcp=receives_mcp,
            has_lsp_config=has_config,
            recipe_kind=kind,
        )

    def status(self, context: dict[str, Any] | None = None) -> ProviderRecipeResult:
        """Report LSP recipe status for this provider."""
        parts = []
        if self.has_native_lsp:
            parts.append("native LSP provision")
        if self.has_lsp_config:
            parts.append("LSP config sync")
        if not self.receives_ag_lsp_mcp:
            parts.append("ag-lsp MCP opted out")

        return ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            status=" | ".join(parts) if parts else "no LSP support",
            source_url="",
            source_date="",
            action_needed="" if parts else "provider has no LSP integration",
        )


def map_lsp_fields_to_recipe_concepts(
    provider_id: str,
    has_on_lsp_enabled: bool,
    receive_lsp_mcp: bool,
    has_language_servers_config: bool,
) -> dict[str, Any]:
    """Document how current LSP fields map to provider recipe concepts.

    Returns a dict describing the mapping for documentation/audit purposes.
    """
    mapping = {
        "provider_id": provider_id,
        "language_servers_config": "config recipe (provider-owned MCP config writes)",
        "on_lsp_enabled": "native provision recipe (provider-specific LSP setup)",
        "receive_lsp_mcp": "generic MCP fallback policy (opt-out of ag-lsp projection)",
    }

    if has_on_lsp_enabled:
        mapping["dominant_strategy"] = "native_passthrough"
    elif has_language_servers_config:
        mapping["dominant_strategy"] = "mcp_config"
    else:
        mapping["dominant_strategy"] = "guidance_only"

    return mapping


__all__ = [
    "LspRecipeAdapter",
    "map_lsp_fields_to_recipe_concepts",
]
