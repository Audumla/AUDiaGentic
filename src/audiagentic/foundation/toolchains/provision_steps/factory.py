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


def steps_from_defs(
    step_defs: list[dict[str, Any]],
    params: dict[str, str],
    *,
    recipe_id: str | None = None,
    registry: ArtifactRegistry | None = None,
) -> list[ProvisionStep]:
    """Build ProvisionStep instances from a list of YAML step definitions.

    Steps without an explicit ``id`` are assigned ``step-<index>``.
    """
    steps: list[ProvisionStep] = []
    for i, defn in enumerate(step_defs):
        step_data = dict(defn)
        if "id" not in step_data:
            step_data["id"] = f"step-{i}"
        steps.append(
            provision_step_from_dict(
                step_data,
                params,
                registry=registry,
                recipe_id=recipe_id,
            )
        )
    return steps


def substitute_params(text: str, params: dict[str, str]) -> str:
    """Replace ``{KEY}`` placeholders in a raw string, leniently.

    Unlike the strict per-step substitution (which rejects unknown
    placeholders in step definitions), this leaves unknown or unset
    placeholders literal — callers use it for free-form command strings
    (e.g. status probes) where an absent optional value must not fail.
    """
    if not text:
        return text
    for key, value in params.items():
        text = text.replace(f"{{{key}}}", value)
    return text
