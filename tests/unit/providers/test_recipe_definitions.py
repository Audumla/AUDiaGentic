from __future__ import annotations

from typing import Any

import pytest

from audiagentic.components.providers.services.recipe_definitions import (
    ProviderAutomationRegistry,
    RecipeDefinition,
    load_recipe_definition,
    validate_recipe_definition_payload,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _payload(
    *,
    recipe_id: str = "fixture-cli",
    provider_id: str = "fixture",
    family_id: str = "cli",
    modes: list[str] | None = None,
    payload_contract: str = "provider-cli-payload/v1",
    result_contract: str = "provider-cli-result/v1",
    ownership_scope_required: bool = False,
) -> dict[str, Any]:
    return {
        "recipe-id": recipe_id,
        "provider-id": provider_id,
        "family-id": family_id,
        "supported-modes": modes or ["plan", "apply", "prune", "status"],
        "payload-contract": payload_contract,
        "result-contract": result_contract,
        "recipe-version": "1",
        "ownership-scope-required": ownership_scope_required,
        "provenance-ref": "docs/reference/provider-evidence.md#fixture",
    }


@pytest.mark.parametrize(
    ("family_id", "payload_contract", "result_contract"),
    [
        ("cli", "provider-cli-payload/v1", "provider-cli-result/v1"),
        (
            "managed-config",
            "managed-config-payload/v1",
            "managed-config-result/v1",
        ),
        ("generated-surfaces", "surface-payload/v1", "surface-result/v1"),
    ],
)
def test_one_schema_accepts_distinct_family_contracts(
    family_id: str,
    payload_contract: str,
    result_contract: str,
) -> None:
    payload = _payload(
        recipe_id=f"fixture-{family_id}",
        family_id=family_id,
        payload_contract=payload_contract,
        result_contract=result_contract,
    )

    assert validate_recipe_definition_payload(payload) == []
    definition = load_recipe_definition(payload)
    assert definition.payload_contract == payload_contract
    assert definition.result_contract == result_contract


def test_loader_builds_frozen_internal_definition() -> None:
    definition = load_recipe_definition(_payload(modes=["plan", "apply", "status"]))

    assert definition == RecipeDefinition(
        recipe_id="fixture-cli",
        provider_id="fixture",
        family_id="cli",
        supported_modes=("plan", "apply", "status"),
        payload_contract="provider-cli-payload/v1",
        result_contract="provider-cli-result/v1",
        recipe_version="1",
        ownership_scope_required=False,
        provenance_ref="docs/reference/provider-evidence.md#fixture",
    )


@pytest.mark.parametrize("mode", ["install", "repair", "dry_run", "execute"])
def test_schema_rejects_private_or_non_automation_modes(mode: str) -> None:
    issues = validate_recipe_definition_payload(_payload(modes=[mode]))

    assert issues


def test_definition_alone_cannot_enable_execution() -> None:
    definition = load_recipe_definition(_payload())
    registry = ProviderAutomationRegistry(
        known_provider_ids={"fixture"},
        family_contracts={"cli": (definition.payload_contract, definition.result_contract)},
    )

    with pytest.raises(AudiaGenticError, match="RES-PREC-001"):
        registry.dispatch("fixture", "cli", "status", {})


def test_explicit_registration_enables_provider_family_only() -> None:
    calls: list[tuple[str, Any, Any]] = []
    definition = load_recipe_definition(_payload())
    registry = ProviderAutomationRegistry(
        known_provider_ids={"fixture"},
        family_contracts={"cli": (definition.payload_contract, definition.result_contract)},
    )

    def implementation(mode: str, payload: Any, scope: Any) -> dict[str, Any]:
        calls.append((mode, payload, scope))
        return {"family": "cli", "mode": mode, "payload": payload}

    registry.register(definition, implementation)
    result = registry.dispatch("fixture", "cli", "apply", {"desired": "present"})

    assert result == {
        "family": "cli",
        "mode": "apply",
        "payload": {"desired": "present"},
    }
    assert calls == [("apply", {"desired": "present"}, None)]
    assert registry.definition_for("fixture", "cli") is definition


def test_duplicate_provider_family_registration_fails() -> None:
    definition = load_recipe_definition(_payload())
    registry = ProviderAutomationRegistry(
        known_provider_ids={"fixture"},
        family_contracts={"cli": (definition.payload_contract, definition.result_contract)},
    )
    def implementation(mode, payload, scope):
        return None

    registry.register(definition, implementation)

    with pytest.raises(AudiaGenticError, match="CON-PREC-001"):
        registry.register(definition, implementation)


def test_unknown_provider_and_family_fail_registration() -> None:
    definition = load_recipe_definition(_payload())
    unknown_provider_registry = ProviderAutomationRegistry(
        known_provider_ids=set(),
        family_contracts={"cli": (definition.payload_contract, definition.result_contract)},
    )
    with pytest.raises(AudiaGenticError, match="VAL-PREC-003"):
        unknown_provider_registry.register(definition, lambda mode, payload, scope: None)

    unknown_family_registry = ProviderAutomationRegistry(
        known_provider_ids={"fixture"},
        family_contracts={},
    )
    with pytest.raises(AudiaGenticError, match="VAL-PREC-004"):
        unknown_family_registry.register(definition, lambda mode, payload, scope: None)


@pytest.mark.parametrize("family_id", ["query", "catalog-refresh", "agent-execution"])
def test_non_automation_categories_cannot_register(family_id: str) -> None:
    definition = load_recipe_definition(_payload(family_id=family_id))
    registry = ProviderAutomationRegistry(
        known_provider_ids={"fixture"},
        family_contracts={},
    )

    with pytest.raises(AudiaGenticError, match="VAL-PREC-004"):
        registry.register(definition, lambda mode, payload, scope: None)


def test_supported_modes_and_ownership_scope_are_enforced() -> None:
    definition = load_recipe_definition(
        _payload(modes=["plan", "apply", "prune"], ownership_scope_required=True)
    )
    registry = ProviderAutomationRegistry(
        known_provider_ids={"fixture"},
        family_contracts={"cli": (definition.payload_contract, definition.result_contract)},
    )
    registry.register(
        definition,
        lambda mode, payload, scope: {"mode": mode, "scope": scope},
    )

    with pytest.raises(AudiaGenticError, match="CON-PREC-002"):
        registry.dispatch("fixture", "cli", "status", {})
    with pytest.raises(AudiaGenticError, match="VAL-PREC-007"):
        registry.dispatch("fixture", "cli", "apply", {})

    assert registry.dispatch(
        "fixture",
        "cli",
        "prune",
        {},
        ownership_scope={"owner": "fixture"},
    ) == {"mode": "prune", "scope": {"owner": "fixture"}}


def test_family_contract_mismatch_fails_registration() -> None:
    definition = load_recipe_definition(_payload())
    registry = ProviderAutomationRegistry(
        known_provider_ids={"fixture"},
        family_contracts={"cli": ("different-payload/v1", "different-result/v1")},
    )

    with pytest.raises(AudiaGenticError, match="VAL-PREC-005"):
        registry.register(definition, lambda mode, payload, scope: None)
