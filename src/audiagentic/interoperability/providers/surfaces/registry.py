from __future__ import annotations

import importlib

from .base import ProviderContributionRenderer, ProviderSurfaceRenderer

_renderer_registry: dict[str, ProviderSurfaceRenderer] = {}
_contribution_renderer_registry: dict[str, ProviderContributionRenderer] = {}
_providers_imported = False


def _ensure_provider_modules_registered() -> None:
    global _providers_imported
    if _providers_imported:
        return
    importlib.import_module("audiagentic.interoperability.providers")
    _providers_imported = True


def register_renderer(provider_id: str, renderer: ProviderSurfaceRenderer) -> None:
    _renderer_registry[provider_id] = renderer


def load_renderer_registry() -> dict[str, ProviderSurfaceRenderer]:
    _ensure_provider_modules_registered()
    return dict(_renderer_registry)


def register_contribution_renderer(provider_id: str, renderer: ProviderContributionRenderer) -> None:
    _contribution_renderer_registry[provider_id] = renderer


def load_contribution_renderer_registry() -> dict[str, ProviderContributionRenderer]:
    _ensure_provider_modules_registered()
    return dict(_contribution_renderer_registry)
