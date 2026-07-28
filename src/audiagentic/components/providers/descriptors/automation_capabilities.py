"""Typed, declarative provider automation capability declarations."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError

AUTOMATION_MODES = frozenset({"plan", "apply", "prune", "status", "upgrade-status", "upgrade"})


def _validate_family_in_catalogue(capability: ProviderAutomationCapability) -> None:
    """VAL-PCAP-011: family must exist in _families.yaml with matching contracts."""
    from .capability_catalogue import validate_family_declaration

    try:
        validate_family_declaration(
            capability.family_id,
            payload_contract=capability.payload_contract,
            result_contract=capability.result_contract,
            supported_modes=capability.supported_modes,
        )
    except Exception as exc:  # CatalogueError → VAL-PCAP-011
        raise _error(
            str(exc),
            family_id=capability.family_id,
        ) from None


_CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts"


@dataclass(frozen=True)
class ProviderAutomationCapability:
    """One explicitly supported provider automation family.

    This declaration is discoverable configuration, not execution authority.
    Code must still explicitly register a matching provider/family handler.
    """

    family_id: str
    supported_modes: tuple[str, ...]
    payload_contract: str
    result_contract: str
    ownership_scope_required: bool


def validate_automation_capabilities(
    capabilities: Collection[ProviderAutomationCapability],
) -> None:
    """Reject ambiguous or non-automation declarations at descriptor boundary."""
    seen: set[str] = set()
    for capability in capabilities:
        if not capability.family_id:
            raise _error("automation capability requires family_id")
        if capability.family_id in seen:
            raise _error(
                "duplicate automation capability family_id",
                family_id=capability.family_id,
            )
        seen.add(capability.family_id)
        if not capability.supported_modes:
            raise _error(
                "automation capability requires supported_modes",
                family_id=capability.family_id,
            )
        unsupported = sorted(set(capability.supported_modes) - AUTOMATION_MODES)
        if unsupported:
            raise _error(
                "automation capability declares non-public mode",
                family_id=capability.family_id,
                modes=unsupported,
            )
        if len(capability.supported_modes) != len(set(capability.supported_modes)):
            raise _error(
                "automation capability declares duplicate mode",
                family_id=capability.family_id,
            )
        if not capability.payload_contract or not capability.result_contract:
            raise _error(
                "automation capability requires payload and result contracts",
                family_id=capability.family_id,
            )
        for contract_ref in (
            capability.payload_contract,
            capability.result_contract,
        ):
            _validate_contract_ref(contract_ref, capability.family_id)

        # VAL-PCAP-011: family_id must exist in _families.yaml
        _validate_family_in_catalogue(capability)


def _validate_contract_ref(contract_ref: str, family_id: str) -> None:
    """Resolve declared v1 contract refs to checked provider JSON schemas."""
    name, separator, version = contract_ref.partition("/")
    if not separator or not name or not version.startswith("v"):
        raise _error(
            "automation capability contract ref must use <name>/vN",
            family_id=family_id,
            contract_ref=contract_ref,
        )
    path = _CONTRACT_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise _error(
            "automation capability contract schema is missing",
            family_id=family_id,
            contract_ref=contract_ref,
        )
    try:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise _error(
            "automation capability contract schema is invalid",
            family_id=family_id,
            contract_ref=contract_ref,
        ) from exc


def _error(message: str, **details: object) -> AudiaGenticError:
    return AudiaGenticError(
        code="VAL-PCAP-010",
        kind="providers",
        message=message,
        details=details or None,
    )


__all__ = [
    "AUTOMATION_MODES",
    "ProviderAutomationCapability",
    "validate_automation_capabilities",
]
