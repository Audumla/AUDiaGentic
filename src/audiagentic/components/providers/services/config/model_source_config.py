"""Canonical load/validate/write API for the project model-sources contract.

Persisted file contract (MO01 step 9): exactly
``.audiagentic/config/model-sources.yaml`` with top-level shape
``{contract-version: v1, sources: {<source-id>: <source>}}``.

The schema (``contracts/model-sources.schema.json``) is intentionally
component-only — not mirrored into ``foundation/contracts/schemas`` — because
no foundation consumer exists yet (MO01 step 11). Validation therefore reads
the schema file directly rather than going through
``foundation.contracts.schema_registry``, which only resolves schemas already
mirrored there.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import load_yaml_value, save_yaml_file

_model_sources_error = make_error_factory("VAL", "MEP", "providers")

_CONTRACT_VERSION = "v1"
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "model-sources.schema.json"
_RELATIVE_CONFIG_PATH = Path(".audiagentic") / "config" / "model-sources.yaml"


def _schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def model_sources_path(project_root: Path) -> Path:
    """Resolve the canonical model-sources.yaml path for *project_root*."""
    return project_root / _RELATIVE_CONFIG_PATH


def validate_model_sources(payload: Any) -> list[str]:
    """Return sorted schema-validation error messages (empty list if valid)."""
    validator = Draft202012Validator(_schema())
    return sorted(error.message for error in validator.iter_errors(payload))


def _empty_document() -> dict[str, Any]:
    return {"contract-version": _CONTRACT_VERSION, "sources": {}}


def load_model_sources(project_root: Path) -> dict[str, Any]:
    """Load and validate the project's model-sources document.

    A missing file returns an empty valid v1 document. A malformed or
    schema-invalid file raises ``VAL-MEP-001`` — never silently substitutes
    an empty document for content that exists but is broken.
    """
    path = model_sources_path(project_root)
    if not path.exists():
        return _empty_document()

    payload = load_yaml_value(path, default=None)
    if payload is None:
        return _empty_document()

    issues = validate_model_sources(payload)
    if issues:
        raise _model_sources_error(
            1,
            "model-sources.yaml failed schema validation",
            path=str(path),
            issues=issues,
        )
    return payload


def write_model_sources(project_root: Path, payload: dict[str, Any]) -> None:
    """Validate and atomically write the project's model-sources document."""
    issues = validate_model_sources(payload)
    if issues:
        raise _model_sources_error(
            1,
            "model-sources.yaml failed schema validation",
            issues=issues,
        )
    save_yaml_file(model_sources_path(project_root), payload, atomic=True)


__all__ = [
    "load_model_sources",
    "model_sources_path",
    "validate_model_sources",
    "write_model_sources",
]
