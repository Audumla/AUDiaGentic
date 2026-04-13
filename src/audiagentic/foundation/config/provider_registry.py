"""Provider registry and descriptor validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema


def validate_descriptor(payload: dict[str, Any]) -> list[str]:
    schema = read_schema("provider-descriptor")
    validator = Draft202012Validator(schema)
    return sorted(error.message for error in validator.iter_errors(payload))


def load_provider_registry(descriptors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for payload in descriptors:
        issues = validate_descriptor(payload)
        if issues:
            raise AudiaGenticError(
                code="PRV-VALIDATION-001",
                kind="validation",
                message="provider descriptor failed validation",
                details={"issues": issues, "provider-id": payload.get("provider-id")},
            )
        provider_id = payload["provider-id"]
        if provider_id in registry:
            raise AudiaGenticError(
                code="PRV-BUSINESS-001",
                kind="business-rule",
                message="duplicate provider-id in registry",
                details={"provider-id": provider_id},
            )
        registry[provider_id] = dict(payload)
    return registry
