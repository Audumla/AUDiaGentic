from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import (
    AudiaGenticError,
    ERROR_ENVELOPE_SCHEMA,
    to_error_envelope,
)

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_error_envelope_valid_fixture() -> None:
    payload = _load(FIXTURES / "error-envelope.valid.json")
    validator = Draft202012Validator(ERROR_ENVELOPE_SCHEMA)
    errors = list(validator.iter_errors(payload))
    assert not errors


def test_error_envelope_invalid_fixture_fails() -> None:
    payload = _load(FIXTURES / "error-envelope.invalid.json")
    validator = Draft202012Validator(ERROR_ENVELOPE_SCHEMA)
    errors = list(validator.iter_errors(payload))
    assert errors


def test_to_error_envelope_matches_fixture() -> None:
    error = AudiaGenticError(
        code="FND-VALIDATION-001",
        kind="validation",
        message="project config failed validation",
        details={"field": "workflow-profile"},
    )
    payload = to_error_envelope(error)
    expected = _load(FIXTURES / "error-envelope.valid.json")
    assert payload == expected
