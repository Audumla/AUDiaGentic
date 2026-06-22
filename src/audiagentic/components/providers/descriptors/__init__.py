"""Provider descriptor types and registry.

Individual providers register themselves via their own silo packages.
Import `audiagentic.components.providers` to trigger all registrations.
"""

from __future__ import annotations

from .base import (
    AgentFile,
    HostCapability,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from .registry import all_descriptors, get_descriptor, interrogate, provider_alias_map, register

__all__ = [
    "AgentFile",
    "HostCapability",
    "ProviderDescriptor",
    "ProviderPermissions",
    "VsCodeExtension",
    "register",
    "get_descriptor",
    "all_descriptors",
    "provider_alias_map",
    "interrogate",
]
