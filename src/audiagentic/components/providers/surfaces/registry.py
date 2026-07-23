from __future__ import annotations

import importlib
import sys

from audiagentic.foundation.registry_utils import Registry

from .base import ProviderContributionRenderer, ProviderSurfaceRenderer

_providers_imported = False


def _ensure_provider_modules_registered() -> None:
    global _providers_imported
    if _providers_imported:
        adapters = sys.modules.get("audiagentic.components.providers.adapters")
        if adapters is not None:
            load_providers = getattr(adapters, "load_providers", None)
            if callable(load_providers):
                # Registry.reset() already removed the old registrations. Reload
                # custom surface modules, whose import-time registrations would
                # otherwise remain cached, then rebuild descriptor-driven ones.
                # Do not clear here: callers may have registered an intentional
                # custom renderer before the first lazy read, and custom wins.
                for module_name, module in list(sys.modules.items()):
                    if (
                        module_name.startswith("audiagentic.components.providers.adapters.")
                        and module_name.endswith(".surface")
                    ):
                        importlib.reload(module)
                load_providers()
                _renderer_registry._loaded = True
                _contribution_renderer_registry._loaded = True
        return
    importlib.import_module("audiagentic.components.providers")
    _providers_imported = True
    # The package may already have been imported through another provider API
    # before this lazy registry was read. In that case import_module is a no-op
    # and a preceding reset left the registry empty, so explicitly repopulate it.
    if not _renderer_registry._items and not _contribution_renderer_registry._items:
        adapters = importlib.import_module("audiagentic.components.providers.adapters")
        adapters.load_providers()
    # Both registries are populated by this one loader. Mark the pair together
    # so reading the other registry cannot repeat import-time registration.
    _renderer_registry._loaded = True
    _contribution_renderer_registry._loaded = True


_renderer_registry: Registry[ProviderSurfaceRenderer] = Registry(
    loader=_ensure_provider_modules_registered,
)
_contribution_renderer_registry: Registry[ProviderContributionRenderer] = Registry(
    loader=_ensure_provider_modules_registered,
)


def register_renderer(provider_id: str, renderer: ProviderSurfaceRenderer) -> None:
    _renderer_registry.register(provider_id, renderer)


def renderer_registered(provider_id: str) -> bool:
    return _renderer_registry.is_registered(provider_id)


def contribution_renderer_registered(provider_id: str) -> bool:
    return _contribution_renderer_registry.is_registered(provider_id)


def load_renderer_registry() -> dict[str, ProviderSurfaceRenderer]:
    return _renderer_registry.all()


def register_contribution_renderer(provider_id: str, renderer: ProviderContributionRenderer) -> None:
    _contribution_renderer_registry.register(provider_id, renderer)


def load_contribution_renderer_registry() -> dict[str, ProviderContributionRenderer]:
    return _contribution_renderer_registry.all()
