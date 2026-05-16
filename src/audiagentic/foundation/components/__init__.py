"""Foundation component registry — pure read API, no lifecycle operations.

Components self-register from their own packages by importing
audiagentic.foundation.components.registry.register.
"""
from __future__ import annotations

from .base import (
    MODE_CREATE_IF_MISSING,
    MODE_GENERATED_MANAGED,
    MODE_REQUIRED_MANAGED,
    MODE_RUNTIME_ONLY,
    ComponentDescriptor,
    ComponentFile,
)
from .registry import (
    all_descriptors,
    get_descriptor,
    is_enabled,
    is_installed,
    register,
)

__all__ = [
    "ComponentDescriptor",
    "ComponentFile",
    "MODE_REQUIRED_MANAGED",
    "MODE_CREATE_IF_MISSING",
    "MODE_GENERATED_MANAGED",
    "MODE_RUNTIME_ONLY",
    "register",
    "get_descriptor",
    "all_descriptors",
    "is_installed",
    "is_enabled",
]
