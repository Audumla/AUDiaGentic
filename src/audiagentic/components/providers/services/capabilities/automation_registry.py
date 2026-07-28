"""Composition root for provider automation: one table, one registration loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import generated_surface_family
from .cli_lifecycle_handler import _make_cli_handler
from .model_projection_handler import (
    _make_model_projection_handler,
)
from .recipe_definitions import (
    ProviderAutomationRegistry,
    RecipeDefinition,
    RecipeHandler,
)
from .self_provided_lsp_handler import (
    _make_self_provided_lsp_handler,
)


@dataclass(frozen=True)
class FamilyRegistrar:
    """One Pattern A family's composition entry.

    ``family_id`` is the family identifier; contracts are resolved from
    _families.yaml at load time (PC01). ``eligible`` decides which descriptors
    carry the underlying mechanism, and ``make_handler`` binds per-provider
    context into a RecipeHandler.
    """

    family_id: str
    eligible: Callable[[Any], bool]
    make_handler: Callable[[str, Path], RecipeHandler]


# Pattern A families only. Descriptor-backed generic families (managed-mcp,
# plugin-entry) need no registration per MA20 step 8 — they validate their
# declaration at call time and are reached through providers_api.
_REGISTRARS: tuple[FamilyRegistrar, ...] = (
    FamilyRegistrar(
        family_id="cli-lifecycle",
        eligible=lambda desc: desc.cli_install is not None,
        make_handler=_make_cli_handler,
    ),
    FamilyRegistrar(
        family_id="generated-surfaces",
        eligible=lambda desc: True,
        make_handler=lambda _pid, root: generated_surface_family.make_generated_surface_handler(
            root
        ),
    ),
    FamilyRegistrar(
        family_id="model-projection",
        eligible=lambda desc: desc.model_config is not None,
        make_handler=_make_model_projection_handler,
    ),
    FamilyRegistrar(
        family_id="self-provided-lsp",
        eligible=lambda desc: desc.on_lsp_enabled is not None,
        make_handler=_make_self_provided_lsp_handler,
    ),
)


def _resolve_family(family_id: str):
    """Resolve a family declaration from the catalogue (config-based)."""
    from audiagentic.components.providers.descriptors.capability_catalogue import (
        get_catalogue,
    )

    return get_catalogue().families[family_id]


def _make_definition(
    family_id: str, provider_id: str, *, ownership_scope_required: bool = False
) -> RecipeDefinition:
    """Build a RecipeDefinition from config-based family declaration."""
    family = _resolve_family(family_id)
    return RecipeDefinition(
        recipe_id=f"{provider_id}.{family_id}",
        provider_id=provider_id,
        family_id=family_id,
        supported_modes=family.supported_modes,
        payload_contract=family.payload_contract,
        result_contract=family.result_contract,
        recipe_version="1",
        ownership_scope_required=ownership_scope_required,
    )


def build_automation_registry(project_root: Path) -> ProviderAutomationRegistry:
    """Build the provider automation registry for the given project root.

    Loads descriptors, resolves each family's contracts from _families.yaml,
    and registers a handler for every provider that both declares the capability
    and carries the underlying descriptor mechanism. ``register`` rejects any
    declaration that disagrees with the family config, so configuration cannot
    widen a family (VAL-PCAP-011).
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptors = all_descriptors()

    registry = ProviderAutomationRegistry(
        known_provider_ids=set(descriptors),
        family_contracts={r.family_id: _resolve_family(r.family_id).contracts for r in _REGISTRARS},
        provider_capabilities={
            pid: tuple(desc.automation_capabilities) for pid, desc in descriptors.items()
        },
    )

    for registrar in _REGISTRARS:
        family_id = registrar.family_id
        for pid, desc in descriptors.items():
            declaration = desc.automation_capability(family_id)
            if declaration is None:
                continue
            if not registrar.eligible(desc):
                continue
            registry.register(
                _make_definition(
                    family_id,
                    pid,
                    ownership_scope_required=declaration.ownership_scope_required,
                ),
                registrar.make_handler(pid, project_root),
            )

    return registry


__all__ = ["FamilyRegistrar", "build_automation_registry"]
