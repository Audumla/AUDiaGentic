from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.validation.validate_schemas as validate_schemas


def test_all_fixtures_validate() -> None:
    findings = validate_schemas.validate_fixtures()
    assert findings == []


def test_invalid_fixture_reports_path() -> None:
    fixture = validate_schemas.FIXTURES_DIR / "approval-request.invalid.json"
    schema = validate_schemas.SCHEMA_DIR / "approval-request.schema.json"
    errors = validate_schemas.validate_fixture(schema, fixture)
    assert errors
    assert all("path" in err for err in errors)


def test_validator_does_not_mutate_files(tmp_path: Path) -> None:
    schema = validate_schemas.SCHEMA_DIR / "approval-request.schema.json"
    fixture = validate_schemas.FIXTURES_DIR / "approval-request.valid.json"
    schema_before = schema.read_text(encoding="utf-8")
    fixture_before = fixture.read_text(encoding="utf-8")
    _ = validate_schemas.validate_fixture(schema, fixture)
    assert schema.read_text(encoding="utf-8") == schema_before
    assert fixture.read_text(encoding="utf-8") == fixture_before
