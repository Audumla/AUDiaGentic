"""Hindsight aggregate status vocabulary and builder."""
from __future__ import annotations

from enum import Enum
from typing import Any

from audiagentic.components.providers.services.recipes import (
    ProviderRecipeRegistry,
    RecipeState,
)


class HindsightStatusState(str, Enum):
    """Aggregate status for a provider's Hindsight integration.

    Distinct from RecipeState (per-recipe lifecycle state). This value summarizes
    whether the provider's Hindsight recipe set is active, inactive, or absent
    from the registry — useful for CLI/dashboard consumers that need a single
    machine-readable token rather than per-recipe details.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    NOT_REGISTERED = "not_registered"


def build_hindsight_status(
    registry: ProviderRecipeRegistry,
    provider_id: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build Hindsight status for a specific provider from the recipe registry."""
    recipes = registry.list_for_provider(provider_id, "hindsight")
    if not recipes:
        return {
            "provider_id": provider_id,
            "hindsight": {
                "status": HindsightStatusState.NOT_REGISTERED.value,
                "action_needed": "no Hindsight recipe for this provider",
            },
        }

    results = []
    for recipe in recipes:
        status = registry.status(
            recipe.provider_id,
            recipe.capability_id,
            recipe.backend_id,
            context,
        )
        if status is not None:
            row = getattr(recipe, "_row", None)
            source_status = getattr(row, "source_status", "") or "unconfirmed"
            # registry.status returns a stamped ProviderRecipeResult (SL11
            # boundary), so provenance fields are read directly.
            results.append({
                "provider_id": recipe.provider_id,
                "capability_id": recipe.capability_id,
                "kind": recipe.recipe_kind.value,
                "state": status.state.value,
                "status": status.status,
                "action_needed": status.action_needed,
                "source_url": status.source_url,
                "source_date": status.source_date,
                "source_status": source_status,
                "artifacts_owned": list(status.artifacts_owned),
            })

    is_active = any(r["state"] == RecipeState.VERIFIED.value for r in results)
    return {
        "provider_id": provider_id,
        "hindsight": {
            "status": HindsightStatusState.ACTIVE.value if is_active else HindsightStatusState.INACTIVE.value,
            "recipes": results,
        },
    }


__all__ = [
    "HindsightStatusState",
    "build_hindsight_status",
]
