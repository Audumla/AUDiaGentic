"""Self-provided LSP support automation family pin."""
from __future__ import annotations

from audiagentic.components.providers.services.recipe_definitions import FamilyPin

FAMILY_ID = "self-provided-lsp"

PIN = FamilyPin(
    family_id=FAMILY_ID,
    payload_contract="provider-self-provided-lsp-payload/v1",
    result_contract="provider-self-provided-lsp-result/v1",
    supported_modes=("apply", "status"),
    ownership_scope_required=False,
)

__all__ = ["FAMILY_ID", "PIN"]
