"""MA21 generated-surface recipe family — handler and public API adapter.

Family declaration is in _families.yaml (config-based, PC01).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.generated_surface import (
    GeneratedSurfaceRequest,
    GeneratedSurfaceResult,
)
from audiagentic.components.providers.services.recipe_definitions import (
    FamilyPin,
    RecipeHandler,
)

FAMILY_ID = "generated-surfaces"

# Compatibility: PIN resolved from _families.yaml at access time.
class _LazyPin:
    """Lazy-loaded FamilyPin proxy — resolves from config on first attribute access."""

    def __init__(self, family_id: str):
        self._family_id = family_id
        self._pin: FamilyPin | None = None

    def _resolve(self) -> FamilyPin:
        if self._pin is None:
            from audiagentic.components.providers.descriptors.capability_catalogue import (
                get_catalogue,
            )

            family = get_catalogue().families[self._family_id]
            self._pin = FamilyPin(
                family_id=self._family_id,
                payload_contract=family.payload_contract,
                result_contract=family.result_contract,
                supported_modes=family.supported_modes,
                ownership_scope_required=family.ownership_scope_required,
            )
        return self._pin

    def __getattr__(self, name: str):
        return getattr(self._resolve(), name)

PIN = _LazyPin(FAMILY_ID)


def make_generated_surface_handler(project_root: Path) -> RecipeHandler:
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
    "make_generated_surface_handler",
]
