"""Composition root for provider automation: one table, one registration loop."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services import (
    cli_lifecycle_family,
    generated_surface_family,
    model_projection_family,
    self_provided_lsp_family,
)
from audiagentic.components.providers.services.cli_lifecycle_handler import _make_cli_handler
from audiagentic.components.providers.services.model_projection_handler import (
    _make_model_projection_handler,
)
from audiagentic.components.providers.services.recipe_definitions import (
    FamilyPin,
    ProviderAutomationRegistry,
    RecipeHandler,
)
from audiagentic.components.providers.services.self_provided_lsp_handler import (
    _make_self_provided_lsp_handler,
)


@dataclass(frozen=True)
class FamilyRegistrar:
    """One Pattern A family's composition entry.

    ``pin`` is the family's authoritative contract statement, ``eligible``
    decides which descriptors carry the underlying mechanism, and
    ``make_handler`` binds per-provider context into a RecipeHandler.
    """

    pin: FamilyPin
    eligible: Callable[[Any], bool]
    make_handler: Callable[[str, Path], RecipeHandler]


# Pattern A families only. Descriptor-backed generic families (managed-mcp,
# plugin-entry, language-server-projection) need no registration per MA20 step 8
# — they validate their declaration at call time and are reached through
# providers_api.
_REGISTRARS: tuple[FamilyRegistrar, ...] = (
    FamilyRegistrar(
        pin=cli_lifecycle_family.PIN,
        eligible=lambda desc: desc.cli_install is not None,
        make_handler=_make_cli_handler,
    ),
    FamilyRegistrar(
        pin=generated_surface_family.PIN,
        eligible=lambda desc: True,
        make_handler=lambda _pid, root: (
            generated_surface_family.make_generated_surface_handler(root)
        ),
    ),
    FamilyRegistrar(
        pin=model_projection_family.PIN,
        eligible=lambda desc: desc.model_config is not None,
        make_handler=_make_model_projection_handler,
    ),
    FamilyRegistrar(
        pin=self_provided_lsp_family.PIN,
        eligible=lambda desc: desc.on_lsp_enabled is not None,
        make_handler=_make_self_provided_lsp_handler,
    ),
)


def build_automation_registry(project_root: Path) -> ProviderAutomationRegistry:
    """Build the provider automation registry for the given project root.

    Loads descriptors, pins each Pattern A family's contracts, and registers a
    handler for every provider that both declares the capability and carries the
    underlying descriptor mechanism. ``register`` rejects any declaration that
    disagrees with the family pin, so configuration cannot widen a family.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptors = all_descriptors()

    registry = ProviderAutomationRegistry(
        known_provider_ids=set(descriptors),
        family_contracts={r.pin.family_id: r.pin.contracts for r in _REGISTRARS},
        provider_capabilities={
            pid: tuple(desc.automation_capabilities) for pid, desc in descriptors.items()
        },
    )

    for registrar in _REGISTRARS:
        family_id = registrar.pin.family_id
        for pid, desc in descriptors.items():
            if desc.automation_capability(family_id) is None:
                continue
            if not registrar.eligible(desc):
                continue
            registry.register(
                registrar.pin.definition(pid),
                registrar.make_handler(pid, project_root),
            )

    return registry


__all__ = ["FamilyRegistrar", "build_automation_registry"]
