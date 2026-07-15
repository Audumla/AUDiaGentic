from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.descriptors.registry import all_descriptors
from audiagentic.components.providers.services.cli_lifecycle_family import (
    FAMILY_ID as CLI_FAMILY_ID,
    cli_lifecycle_definition,
    cli_lifecycle_family_contracts,
)
from audiagentic.components.providers.services.cli_lifecycle_handler import (
    _make_cli_handler,
)
from audiagentic.components.providers.services.generated_surface_family import (
    generated_surface_family_contracts,
)
from audiagentic.components.providers.services.recipe_definitions import (
    ProviderAutomationRegistry,
)


def build_automation_registry(project_root: Path) -> ProviderAutomationRegistry:
    """Build the provider automation registry for the given project root.

    Loads descriptors, collects capability declarations and open family contract
    contributions, and registers executable handlers. Only CLI handlers are
    registered now; managed-mcp/plugin-entry remain descriptor-backed generic
    services until their owning migration explicitly adopts registry composition.
    """
    descriptors = all_descriptors()
    known_provider_ids = set(descriptors.keys())

    family_contracts = {}
    family_contracts.update(cli_lifecycle_family_contracts())
    family_contracts.update(generated_surface_family_contracts())

    provider_capabilities = {}
    for pid, desc in descriptors.items():
        provider_capabilities[pid] = tuple(desc.automation_capabilities)

    registry = ProviderAutomationRegistry(
        known_provider_ids=known_provider_ids,
        family_contracts=family_contracts,
        provider_capabilities=provider_capabilities,
    )

    for pid, desc in descriptors.items():
        if desc.cli_install is None:
            continue
        if desc.automation_capability(CLI_FAMILY_ID) is None:
            continue
        definition = cli_lifecycle_definition(pid)
        handler = _make_cli_handler(pid, project_root)
        registry.register(definition, handler)

    return registry


__all__ = ["build_automation_registry"]
