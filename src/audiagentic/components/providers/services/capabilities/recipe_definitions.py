"""Internal recipe definitions and explicit provider automation registration.

Definitions describe implementations but never enable them. Only
``ProviderAutomationRegistry.register`` binds a validated definition to code.
Public callers never import this module or construct these types.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError

from ...descriptors.automation_capabilities import ProviderAutomationCapability

AUTOMATION_MODES = frozenset({"plan", "apply", "prune", "status", "upgrade-status", "upgrade"})
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "provider-recipe.schema.json"

RecipeHandler = Callable[[str, object, object | None], object]


@dataclass(frozen=True)
class RecipeDefinition:
    """Validated metadata for one provider-family automation implementation."""

    recipe_id: str
    provider_id: str
    family_id: str
    supported_modes: tuple[str, ...]
    payload_contract: str
    result_contract: str
    recipe_version: str
    ownership_scope_required: bool
    provenance_ref: str | None = None


@dataclass(frozen=True)
class FamilyPin:
    """Composition-owned statement of what one automation family implements.

    This is the family's authority, not a copy of provider configuration.
    ``register`` validates each provider's descriptor declaration against the
    definition built from this pin, so a descriptor cannot declare a mode or a
    contract the family does not actually implement (VAL-PREC-009). Deriving
    the pin from descriptors would make that check tautological and let a typo
    redefine the family, so the pin stays in code.
    """

    family_id: str
    payload_contract: str
    result_contract: str
    supported_modes: tuple[str, ...]
    ownership_scope_required: bool = False

    @property
    def contracts(self) -> tuple[str, str]:
        """The (payload, result) entry this family contributes to the contract map."""
        return (self.payload_contract, self.result_contract)

    def definition(self, provider_id: str, *, recipe_version: str = "1") -> RecipeDefinition:
        """Build the inert definition for *provider_id* in this family."""
        return RecipeDefinition(
            recipe_id=f"{provider_id}.{self.family_id}",
            provider_id=provider_id,
            family_id=self.family_id,
            supported_modes=self.supported_modes,
            payload_contract=self.payload_contract,
            result_contract=self.result_contract,
            recipe_version=recipe_version,
            ownership_scope_required=self.ownership_scope_required,
        )


def _error(
    prefix: str,
    number: int,
    message: str,
    **details: Any,
) -> AudiaGenticError:
    return AudiaGenticError(
        code=f"{prefix}-PREC-{number:03d}",
        kind="providers",
        message=message,
        details=details or None,
    )


def recipe_definition_schema() -> dict[str, Any]:
    """Load the provider-owned RecipeDefinition JSON schema."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_recipe_definition_payload(payload: Mapping[str, Any]) -> list[str]:
    """Return deterministic schema findings without enabling automation."""
    validator = Draft202012Validator(recipe_definition_schema())
    return sorted(error.message for error in validator.iter_errors(dict(payload)))


def load_recipe_definition(payload: Mapping[str, Any]) -> RecipeDefinition:
    """Validate and construct an inert internal recipe definition."""
    issues = validate_recipe_definition_payload(payload)
    if issues:
        raise _error(
            "VAL",
            1,
            "provider recipe definition failed schema validation",
            issues=issues,
        )
    return RecipeDefinition(
        recipe_id=str(payload["recipe-id"]),
        provider_id=str(payload["provider-id"]),
        family_id=str(payload["family-id"]),
        supported_modes=tuple(payload["supported-modes"]),
        payload_contract=str(payload["payload-contract"]),
        result_contract=str(payload["result-contract"]),
        recipe_version=str(payload["recipe-version"]),
        ownership_scope_required=bool(payload["ownership-scope-required"]),
        provenance_ref=payload.get("provenance-ref"),
    )


class ProviderAutomationRegistry:
    """Explicit code bindings keyed only by ``(provider_id, family_id)``.

    ``family_contracts`` is an open composition-owned mapping, not an enum or
    closed taxonomy. Presence in that mapping classifies a family as
    automation and pins its family-specific payload/result contracts.
    """

    def __init__(
        self,
        *,
        known_provider_ids: Collection[str],
        family_contracts: Mapping[str, tuple[str, str]],
        provider_capabilities: Mapping[
            str, Collection[ProviderAutomationCapability]
        ],
    ) -> None:
        self._known_provider_ids = frozenset(known_provider_ids)
        self._family_contracts = dict(family_contracts)
        self._provider_capabilities = {
            provider_id: {capability.family_id: capability for capability in capabilities}
            for provider_id, capabilities in provider_capabilities.items()
        }
        self._registrations: dict[
            tuple[str, str], tuple[RecipeDefinition, RecipeHandler]
        ] = {}

    def register(
        self,
        definition: RecipeDefinition,
        implementation: RecipeHandler,
    ) -> None:
        """Bind validated metadata to code; duplicate bindings always fail."""
        if not isinstance(definition, RecipeDefinition):
            raise _error("VAL", 2, "registration requires a RecipeDefinition")
        if definition.provider_id not in self._known_provider_ids:
            raise _error(
                "VAL",
                3,
                "unknown provider in recipe registration",
                **{"provider-id": definition.provider_id},
            )
        declaration = self._provider_capabilities.get(definition.provider_id, {}).get(
            definition.family_id
        )
        if declaration is None:
            raise _error(
                "VAL",
                8,
                "provider has not declared automation capability",
                **{
                    "provider-id": definition.provider_id,
                    "family-id": definition.family_id,
                },
            )
        if (
            declaration.payload_contract != definition.payload_contract
            or declaration.result_contract != definition.result_contract
            or declaration.supported_modes != definition.supported_modes
            or declaration.ownership_scope_required
            != definition.ownership_scope_required
        ):
            raise _error(
                "VAL",
                9,
                "recipe definition does not match provider capability declaration",
                **{
                    "provider-id": definition.provider_id,
                    "family-id": definition.family_id,
                },
            )
        contracts = self._family_contracts.get(definition.family_id)
        if contracts is None:
            raise _error(
                "VAL",
                4,
                "unknown automation family in recipe registration",
                **{"family-id": definition.family_id},
            )
        if contracts != (definition.payload_contract, definition.result_contract):
            raise _error(
                "VAL",
                5,
                "recipe family contract references do not match registration",
                **{
                    "family-id": definition.family_id,
                    "expected-payload": contracts[0],
                    "expected-result": contracts[1],
                },
            )
        if not callable(implementation):
            raise _error("VAL", 6, "recipe implementation must be callable")

        key = (definition.provider_id, definition.family_id)
        if key in self._registrations:
            existing = self._registrations[key][0]
            raise _error(
                "CON",
                1,
                "duplicate provider-family recipe registration",
                **{
                    "provider-id": definition.provider_id,
                    "family-id": definition.family_id,
                    "existing-recipe-id": existing.recipe_id,
                    "recipe-id": definition.recipe_id,
                },
            )
        self._registrations[key] = (definition, implementation)

    def definition_for(self, provider_id: str, family_id: str) -> RecipeDefinition | None:
        registration = self._registrations.get((provider_id, family_id))
        return registration[0] if registration else None

    def dispatch(
        self,
        provider_id: str,
        family_id: str,
        mode: str,
        payload: object,
        *,
        ownership_scope: object | None = None,
    ) -> object:
        """Invoke registered code using a supported semantic mode."""
        registration = self._registrations.get((provider_id, family_id))
        if registration is None:
            raise _error(
                "RES",
                1,
                "provider automation implementation is not registered",
                **{"provider-id": provider_id, "family-id": family_id},
            )
        definition, implementation = registration
        if mode not in AUTOMATION_MODES or mode not in definition.supported_modes:
            raise _error(
                "CON",
                2,
                "unsupported provider automation mode",
                **{
                    "provider-id": provider_id,
                    "family-id": family_id,
                    "mode": mode,
                    "supported-modes": list(definition.supported_modes),
                },
            )
        if definition.ownership_scope_required and ownership_scope is None:
            raise _error(
                "VAL",
                7,
                "provider automation operation requires ownership scope",
                **{"provider-id": provider_id, "family-id": family_id},
            )
        return implementation(mode, payload, ownership_scope)


__all__ = [
    "AUTOMATION_MODES",
    "ProviderAutomationRegistry",
    "RecipeDefinition",
    "load_recipe_definition",
    "recipe_definition_schema",
    "validate_recipe_definition_payload",
]
