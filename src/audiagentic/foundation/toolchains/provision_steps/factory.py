"""Registry-lookup factory for provisioning steps."""
from __future__ import annotations

from typing import Any

from ..artifact_registry import ArtifactRegistry
from .base import _STEP_TYPES, ProvisionStep, _pstep_error


def provision_step_from_dict(
    data: dict[str, Any],
    params: dict[str, str],
    *,
    registry: ArtifactRegistry | None = None,
    recipe_id: str | None = None,
) -> ProvisionStep:
    """Construct a ProvisionStep from a YAML-derived dict via the step registry.

    Args:
        data: Step definition with at least ``type`` and ``id`` keys.
        params: Placeholder values for ``{KEY}`` substitution.
        registry: Optional artifact registry for ownership tracking.
        recipe_id: Recipe identifier for registry association.

    Raises:
        AudiaGenticError: VAL-PSTEP-001 for missing/unknown type, VAL-PSTEP-002
            for missing required fields.
    """
    step_type = data.get("type")
    if not step_type:
        raise _pstep_error(1, "step definition missing 'type' field")

    from_dict = _STEP_TYPES.get(step_type)
    if from_dict is None:
        raise _pstep_error(1, f"unknown step type {step_type!r}")

    return from_dict(data, params, registry, recipe_id)
