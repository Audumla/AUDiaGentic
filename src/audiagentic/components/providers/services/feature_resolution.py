"""Resolve the active impl-scoped provider feature set.

This is the single "what should be projected" source. For every enabled provider
implementation it yields the provider's active impl-scoped features (mcp,
lsp-support, surface, skills). Both the projection path and the parity diff
consume this resolver, so neither re-derives the active set independently.

Separation: capability -> feature *derivation* stays pure in
`descriptors/feature_mapping.py`; this module only reads runtime state (provider
enablement + feature state) and composes the two. It performs no file I/O / no
projection itself.

Parity semantics: an impl-scoped feature is active when its provider is enabled
*unless* feature state explicitly disables it. This preserves today's behaviour
(a provider's capabilities project whenever the provider is enabled) while making
per-capability disable a real, additive control.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.features.state import get_implementation_feature_enabled_explicit

from ..descriptors.base import ProviderDescriptor
from ..descriptors.feature_mapping import impl_features_for
from ..descriptors.registry import all_descriptors
from .provider_config import resolve_provider_enabled


@dataclass(frozen=True)
class ResolvedProviderFeature:
    """One active (provider, impl-scoped feature) pair, with its owning descriptor.

    `descriptor` is carried so the projection layer can reach the provider's
    existing capability writer/remover (mcp_config / language_servers_config /
    agent_files) without this resolver knowing how projection is performed.
    """
    provider_id: str
    kind: str
    feature_id: str
    descriptor: ProviderDescriptor


def _feature_active(project_root: Path, provider_id: str, kind: str, feature_id: str) -> bool:
    explicit = get_implementation_feature_enabled_explicit(
        project_root, COMPONENT_PROVIDERS, provider_id, kind, feature_id
    )
    # Default active when the provider is enabled; only an explicit False disables.
    return explicit is not False


def enabled_provider_ids(project_root: Path) -> set[str]:
    """All providers whose implementation resolves enabled, independent of features.

    For callers that gate on provider enablement directly (e.g. LSP provisioning
    hooks) rather than on a specific feature kind.
    """
    return {
        provider_id
        for provider_id in all_descriptors()
        if resolve_provider_enabled(project_root, provider_id)
    }


def resolve_active_provider_features(project_root: Path) -> list[ResolvedProviderFeature]:
    resolved: list[ResolvedProviderFeature] = []
    for provider_id, descriptor in sorted(all_descriptors().items()):
        if not resolve_provider_enabled(project_root, provider_id):
            continue
        for feature in impl_features_for(descriptor):
            if _feature_active(project_root, provider_id, feature.kind, feature.feature_id):
                resolved.append(
                    ResolvedProviderFeature(
                        provider_id=provider_id,
                        kind=feature.kind,
                        feature_id=feature.feature_id,
                        descriptor=descriptor,
                    )
                )
    return resolved
