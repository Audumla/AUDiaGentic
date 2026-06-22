"""Derive implementation-scoped feature descriptors from a `ProviderDescriptor`.

Single, declarative source for "which provider capabilities are modelled as
foundation features". Each provider capability (MCP config, language-server
config, surface files, skills) becomes an implementation-scoped
`FeatureDescriptor` owned by that provider. The mapping is a data table, not an
imperative branch ladder, and carries no provider-specific literals — adding a
capability is one row.

This module knows only `ProviderDescriptor` (input) and the foundation
`FeatureDescriptor` (output). It performs no registration, state, or projection
work, so it stays pure and trivially testable.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.features.base import FEATURE_SCOPE_IMPLEMENTATION, FeatureDescriptor

from .base import ProviderDescriptor

# Feature kinds emitted for provider capabilities. Defined as constants so callers
# (resolver, projection, tests) reference them symbolically, never as string literals.
KIND_MCP = "mcp"
KIND_LSP_SUPPORT = "lsp-support"
KIND_SURFACE = "surface"
KIND_SKILLS = "skills"


def _surface_ids(descriptor: ProviderDescriptor) -> Sequence[str]:
    """Managed surface files for a provider: agent files plus any instruction file.

    `instruction_file` is unioned in because some providers (e.g. qwen) declare an
    instruction file without listing it among `agent_files`.
    """
    ids = [agent_file.rel_path for agent_file in descriptor.agent_files]
    if descriptor.instruction_file and descriptor.instruction_file not in ids:
        ids.append(descriptor.instruction_file)
    return tuple(ids)


@dataclass(frozen=True)
class CapabilitySpec:
    """One provider capability and how it yields impl-scoped feature ids."""
    kind: str
    feature_ids: Callable[[ProviderDescriptor], Sequence[str]]


# The declarative capability table — the single place that decides which provider
# capabilities are modelled as features. One row per capability.
_CAPABILITIES: tuple[CapabilitySpec, ...] = (
    CapabilitySpec(KIND_MCP, lambda d: (KIND_MCP,) if d.mcp_config is not None else ()),
    CapabilitySpec(
        KIND_LSP_SUPPORT,
        lambda d: (KIND_LSP_SUPPORT,) if d.language_servers_config is not None else (),
    ),
    CapabilitySpec(KIND_SURFACE, _surface_ids),
    CapabilitySpec(KIND_SKILLS, lambda d: (KIND_SKILLS,) if d.skill_surface_path else ()),
)


def impl_features_for(descriptor: ProviderDescriptor) -> list[FeatureDescriptor]:
    """Return the implementation-scoped feature descriptors a provider owns.

    Pure function: derives entirely from the descriptor, registers nothing.
    """
    features: list[FeatureDescriptor] = []
    for capability in _CAPABILITIES:
        for feature_id in capability.feature_ids(descriptor):
            features.append(
                FeatureDescriptor(
                    parent=COMPONENT_PROVIDERS,
                    kind=capability.kind,
                    feature_id=feature_id,
                    scope=FEATURE_SCOPE_IMPLEMENTATION,
                    implementation=descriptor.provider_id,
                )
            )
    return features
