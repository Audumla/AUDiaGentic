"""Model-projection automation family pin."""
from __future__ import annotations

from audiagentic.components.providers.services.recipe_definitions import FamilyPin

FAMILY_ID = "model-projection"

PIN = FamilyPin(
    family_id=FAMILY_ID,
    payload_contract="provider-model-projection-payload/v1",
    result_contract="provider-model-projection-result/v1",
    supported_modes=("plan", "apply", "prune", "status"),
    ownership_scope_required=False,
)

__all__ = ["FAMILY_ID", "PIN"]
