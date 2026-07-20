"""Provider descriptor types and registry.

Individual providers register themselves via their own silo packages.
Import `audiagentic.components.providers` to trigger all registrations.
"""

from __future__ import annotations

from .base import (
    AgentFile,
    CapabilityEvidence,
    HostCapability,
    ProviderCapabilityFact,
    ProviderDescriptor,
    ProviderPermissions,
)
from .registry import all_descriptors, get_descriptor, interrogate, provider_alias_map, register
from .session_surface_declarations import SessionSurfaceDeclaration

__all__ = [
    "AgentFile",
    "CapabilityEvidence",
    "HostCapability",
    "ProviderCapabilityFact",
    "ProviderDescriptor",
    "ProviderPermissions",
    "SessionSurfaceDeclaration",
    "register",
    "get_descriptor",
    "all_descriptors",
    "provider_alias_map",
    "interrogate",
]
