"""Provider registry and descriptor validation."""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema


def validate_descriptor(payload: dict[str, Any]) -> list[str]:
    return validate_with_schema("provider-descriptor", payload)


def load_provider_registry(descriptors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for payload in descriptors:
        issues = validate_descriptor(payload)
        if issues:
            raise AudiaGenticError(
                code="VAL-REGISTRY-001",
                kind="providers",
                message="provider descriptor failed validation",
                details={"issues": issues, "provider-id": payload.get("provider-id")},
            )
        provider_id = payload["provider-id"]
        if provider_id in registry:
            raise AudiaGenticError(
                code="CON-REGISTRY-001",
                kind="providers",
                message="duplicate provider-id in registry",
                details={"provider-id": provider_id},
            )
        registry[provider_id] = dict(payload)
    return registry
