"""Provider adapter implementations.

Importing this package discovers adapter packages via pkgutil and loads
provider descriptors from YAML (config/providers/*.yaml). Surface imports
(catalog, hooks, mcp_format) are preserved for callable resolution.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from ..descriptors.loader import get_providers_config_dir, load_providers_from_directory
from ..descriptors.registry import register


def _discover_adapter_packages() -> dict[str, ModuleType]:
    """Discover adapter packages via pkgutil (surface imports only)."""
    modules: dict[str, ModuleType] = {}
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.startswith("_") or not module_info.ispkg:
            continue
        modules[name] = importlib.import_module(f"{__name__}.{name}")
    return modules


def load_providers() -> None:
    """Load all provider descriptors from YAML and register them.

    Descriptors are loaded from config/providers/*.yaml. Surface modules
    (catalog, hooks, mcp_format) are imported for callable resolution.
    """
    # Import surface modules first (catalog.py, hooks.py, mcp_format.py)
    _ADAPTER_MODULES = _discover_adapter_packages()

    # Load descriptors from YAML
    config_dir = get_providers_config_dir()
    providers = load_providers_from_directory(config_dir)

    # Register each provider descriptor
    for descriptor in providers.values():
        register(descriptor)


# Load providers on import (preserves existing behavior)
load_providers()
