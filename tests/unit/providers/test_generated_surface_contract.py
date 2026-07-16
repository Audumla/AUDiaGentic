from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from audiagentic.components.providers.contracts.generated_surface import (
    GeneratedSurfaceRequest,
    GeneratedSurfaceResult,
)
from audiagentic.components.providers.services.generated_surface_family import (
    FAMILY_ID,
    PIN,
)


def test_generated_surface_contracts_are_serializable_and_schema_valid() -> None:
    contract_dir = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "components" / "providers" / "contracts"
    payload_schema = json.loads(
        (contract_dir / "provider-generated-surface-payload.schema.json").read_text(encoding="utf-8")
    )
    result_schema = json.loads(
        (contract_dir / "provider-generated-surface-result.schema.json").read_text(encoding="utf-8")
    )
    request = GeneratedSurfaceRequest("runtime/default", ("hindsight", "coding-lsp"))
    result = GeneratedSurfaceResult(ok=True, supported=True, planned=True)

    Draft202012Validator(payload_schema).validate(request.to_mapping())
    Draft202012Validator(result_schema).validate(result.to_mapping())


def test_generated_surface_recipe_scaffold_matches_family_contract() -> None:
    definition = PIN.definition("codex")

    assert definition.recipe_id == "codex.generated-surfaces"
    assert definition.provider_id == "codex"
    assert definition.family_id == FAMILY_ID
    assert definition.payload_contract == PIN.payload_contract
    assert definition.result_contract == PIN.result_contract
    assert definition.supported_modes == PIN.supported_modes
    assert definition.ownership_scope_required is True
    assert PIN.contracts == (PIN.payload_contract, PIN.result_contract)
