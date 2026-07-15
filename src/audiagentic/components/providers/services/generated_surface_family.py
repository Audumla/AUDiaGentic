"""MA21 generated-surface recipe family — handler, registration, and public API adapter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.generated_surface import (
    GeneratedSurfaceRequest,
    GeneratedSurfaceResult,
)
from audiagentic.components.providers.services.recipe_definitions import (
    RecipeDefinition,
    RecipeHandler,
)

FAMILY_ID = "generated-surfaces"
PAYLOAD_CONTRACT = "provider-generated-surface-payload/v1"
RESULT_CONTRACT = "provider-generated-surface-result/v1"
SUPPORTED_MODES = ("plan", "apply", "prune", "status")


def generated_surface_definition(provider_id: str) -> RecipeDefinition:
    """Build inert metadata for one explicitly declared provider surface family."""
    return RecipeDefinition(
        recipe_id=f"{provider_id}.generated-surfaces",
        provider_id=provider_id,
        family_id=FAMILY_ID,
        supported_modes=SUPPORTED_MODES,
        payload_contract=PAYLOAD_CONTRACT,
        result_contract=RESULT_CONTRACT,
        recipe_version="1",
        ownership_scope_required=True,
    )


def generated_surface_family_contracts() -> dict[str, tuple[str, str]]:
    """Return the MA20 open-family contract entry for composition."""
    return {FAMILY_ID: (PAYLOAD_CONTRACT, RESULT_CONTRACT)}


def _make_handler(project_root: Path) -> RecipeHandler:
    """Create a recipe handler bound to *project_root*.

    The handler dispatches plan/status (read-only), apply (render desired
    contributions), and prune (remove only owned scope) through the surfaces
    manager and returns a typed GeneratedSurfaceResult.
    """
    from audiagentic.components.providers.surfaces.manager import (
        apply_provider_surfaces,
        plan_provider_surfaces,
        prune_provider_surfaces,
    )

    def handler(mode: str, payload: object, ownership_scope: object | None) -> object:
        if isinstance(payload, GeneratedSurfaceRequest):
            request = payload
        elif isinstance(payload, dict):
            request = GeneratedSurfaceRequest.from_mapping(payload)  # type: ignore[arg-type]
        else:
            return GeneratedSurfaceResult(
                ok=False,
                supported=False,
                error_code="VAL-PREC-001",
            )
        provider_id = request.ownership_scope
        result: dict[str, Any] = {}
        if mode in ("plan", "status"):
            result = plan_provider_surfaces(project_root, provider_id=provider_id)
        elif mode == "apply":
            result = apply_provider_surfaces(project_root, provider_id=provider_id)
        elif mode == "prune":
            result = prune_provider_surfaces(project_root, provider_id=provider_id)
        else:
            return GeneratedSurfaceResult(
                ok=False,
                supported=False,
                error_code="CON-PREC-002",
            )
        return GeneratedSurfaceResult(
            ok=bool(result.get("ok", False)),
            supported=True,
            changed=bool(result.get("written") or result.get("pruned")),
            planned=mode in ("plan", "status"),
            written_paths=tuple(result.get("written", [])),
            removed_paths=tuple(result.get("pruned", [])),
            managed_block_ids=tuple(
                str(block_id)
                for file_info in result.get("files", [])
                for block_id in file_info.get("block-ids", [])
            ),
        )

    return handler


__all__ = [
    "FAMILY_ID",
    "PAYLOAD_CONTRACT",
    "RESULT_CONTRACT",
    "SUPPORTED_MODES",
    "generated_surface_definition",
    "generated_surface_family_contracts",
    "_make_handler",
]
