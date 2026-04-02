"""Provider registry and descriptor validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "provider-descriptor.schema.json"


def validate_descriptor(payload: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
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
