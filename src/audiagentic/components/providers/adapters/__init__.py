"""Provider adapter implementations.

Importing this package discovers adapter packages via pkgutil and loads
provider descriptors from YAML (config/providers/*.yaml). Surface imports
(catalog, hooks, mcp_format) are preserved for callable resolution.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

from ..descriptors.loader import (
    get_load_errors,
    get_providers_config_dir,
    load_providers_from_directory,
)
from ..descriptors.registry import register

logger = logging.getLogger(__name__)


def _discover_adapter_packages() -> dict[str, ModuleType]:
    """Discover adapter packages via pkgutil (surface imports only)."""
    modules: dict[str, ModuleType] = {}
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.startswith("_") or not module_info.ispkg:
            continue
        modules[name] = importlib.import_module(f"{__name__}.{name}")
    return modules


def _register_standard_surfaces(descriptor) -> None:
    """Register descriptor-driven surface renderers (AR03).

    Providers whose descriptor carries a ``surfaces:`` block get the standard
    renderer/contribution renderer with zero Python. Adapters with a custom
    surface.py registered themselves during package import and win.
    """
    from pathlib import Path

    from ..surfaces.base import (
        make_single_file_contribution_renderer,
        make_standard_surface_renderer,
    )
    from ..surfaces.registry import (
        contribution_renderer_registered,
        register_contribution_renderer,
        register_renderer,
        renderer_registered,
    )

    surfaces = descriptor.surfaces or {}
    if not surfaces:
        return
    provider_id = descriptor.provider_id
    if not renderer_registered(provider_id):
        adapter_dir = Path(__file__).parent / provider_id.replace("-", "_")
        register_renderer(
            provider_id,
            make_standard_surface_renderer(
                provider_id,
                style=surfaces.get("renderer", "none"),
                instruction_file=descriptor.instruction_file,
                adapter_dir=adapter_dir,
                launch_example_template=surfaces.get(
                    "launch-example-template", "@{tag}-{provider_id}"
                ),
            ),
        )
    contribution_file = surfaces.get("contribution-file")
    if contribution_file and not contribution_renderer_registered(provider_id):
        register_contribution_renderer(
            provider_id,
            make_single_file_contribution_renderer(contribution_file),
        )


def load_providers() -> None:
    """Load all provider descriptors from YAML and register them.

    Descriptors are loaded from config/providers/*.yaml. Surface modules
    (catalog, hooks, mcp_format) are imported for callable resolution.
    Invalid descriptors are skipped and logged at WARNING level; a summary
    is emitted if any were skipped.
    """
    # Import surface modules first (catalog.py, hooks.py, mcp_format.py)
    _ADAPTER_MODULES = _discover_adapter_packages()

    # Load descriptors from YAML
    config_dir = get_providers_config_dir()
    providers = load_providers_from_directory(config_dir)

    # Register each provider descriptor + any descriptor-driven surfaces
    for descriptor in providers.values():
        register(descriptor)
        _register_standard_surfaces(descriptor)

    # Log summary of skipped providers (if any)
    skipped = get_load_errors()
    if skipped:
        logger.warning(
            "Loaded %d provider(s), skipped %d: %s",
            len(providers),
            len(skipped),
            ", ".join(f"{path.name} ({type(exc).__name__})" for path, exc in skipped),
        )


# Load providers on import (preserves existing behavior)
load_providers()
