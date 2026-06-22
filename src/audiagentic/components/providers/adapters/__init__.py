"""Provider adapter implementations.

Importing this package discovers and imports built-in adapter packages so their
descriptor/surface registrations run.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def _discover_adapter_packages() -> dict[str, ModuleType]:
    modules: dict[str, ModuleType] = {}
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.startswith("_") or not module_info.ispkg:
            continue
        modules[name] = importlib.import_module(f"{__name__}.{name}")
    return modules


_ADAPTER_MODULES = _discover_adapter_packages()
globals().update(_ADAPTER_MODULES)

__all__ = sorted(_ADAPTER_MODULES)
