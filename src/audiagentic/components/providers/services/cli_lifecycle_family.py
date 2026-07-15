from __future__ import annotations

from audiagentic.components.providers.services.recipe_definitions import RecipeDefinition

FAMILY_ID = "cli-lifecycle"
PAYLOAD_CONTRACT = "provider-cli-lifecycle-payload/v1"
RESULT_CONTRACT = "provider-cli-lifecycle-result/v1"
SUPPORTED_MODES = ("plan", "apply", "prune", "status")


def cli_lifecycle_definition(provider_id: str) -> RecipeDefinition:
    """Build inert metadata for one explicitly declared provider CLI family."""
    return RecipeDefinition(
        recipe_id=f"{provider_id}.cli-lifecycle",
        provider_id=provider_id,
        family_id=FAMILY_ID,
        supported_modes=SUPPORTED_MODES,
        payload_contract=PAYLOAD_CONTRACT,
        result_contract=RESULT_CONTRACT,
        recipe_version="1",
        ownership_scope_required=False,
    )


def cli_lifecycle_family_contracts() -> dict[str, tuple[str, str]]:
    """Return the MA20 open-family contract entry for composition."""
    return {FAMILY_ID: (PAYLOAD_CONTRACT, RESULT_CONTRACT)}


__all__ = [
    "FAMILY_ID",
    "PAYLOAD_CONTRACT",
    "RESULT_CONTRACT",
    "SUPPORTED_MODES",
    "cli_lifecycle_definition",
    "cli_lifecycle_family_contracts",
]
