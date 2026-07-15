"""Public providers API boundary tests (MA16)."""

from __future__ import annotations

from audiagentic.components.providers import providers_api


def test_public_api_does_not_export_recipe_construction_or_lifecycle() -> None:
    """Requesters use provider operations, never recipe implementation types."""
    forbidden = {
        "ProviderCapabilityRecipe",
        "ProviderRecipeKind",
        "ProviderRecipeRegistry",
        "ProviderRecipeResult",
    }

    assert forbidden.isdisjoint(providers_api.__all__)
    assert all(not hasattr(providers_api, name) for name in forbidden)
