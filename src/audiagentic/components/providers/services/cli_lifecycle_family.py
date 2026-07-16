"""CLI-lifecycle automation family pin."""
from __future__ import annotations

from audiagentic.components.providers.services.recipe_definitions import FamilyPin

FAMILY_ID = "cli-lifecycle"

PIN = FamilyPin(
    family_id=FAMILY_ID,
    payload_contract="provider-cli-lifecycle-payload/v1",
    result_contract="provider-cli-lifecycle-result/v1",
    supported_modes=("plan", "apply", "prune", "status"),
    ownership_scope_required=False,
)

__all__ = ["FAMILY_ID", "PIN"]
