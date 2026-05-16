"""Provider descriptor types and registry.

Individual providers register themselves via their own silo packages.
Import `audiagentic.interoperability.providers` to trigger all registrations.
"""

from __future__ import annotations

from .base import AgentFile, ProviderDescriptor, ProviderPermissions, VsCodeExtension
from .registry import all_descriptors, get_descriptor, interrogate, register

__all__ = [
    "AgentFile",
    "ProviderDescriptor",
    "ProviderPermissions",
    "VsCodeExtension",
    "register",
    "get_descriptor",
    "all_descriptors",
    "interrogate",
]
