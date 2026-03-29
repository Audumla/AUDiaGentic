"""Validate fixtures against JSON schemas."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
FIXTURES_DIR = REPO_ROOT / "docs" / "examples" / "fixtures"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_path_for_fixture(fixture_path: Path) -> Path:
    name = fixture_path.name
    if name.endswith(".valid.json"):
        stem = name[: -len(".valid.json")]
    elif name.endswith(".invalid.json"):
        stem = name[: -len(".invalid.json")]
    else:
        raise ValueError("fixture file must end in .valid.json or .invalid.json")
    if "." in stem:
        stem = stem.split(".", 1)[0]
    return SCHEMA_DIR / f"{stem}.schema.json"


def validate_fixture(schema_path: Path, fixture_path: Path) -> list[dict[str, str]]:
    schema = _load_json(schema_path)
    payload = _load_json(fixture_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    findings: list[dict[str, str]] = []
    for error in errors:
        path = "/".join([str(item) for item in error.path]) or "$"
        findings.append({"path": path, "message": error.message})
    return findings


def validate_fixtures() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for fixture_path in sorted(FIXTURES_DIR.glob("*.valid.json")):
        schema_path = _schema_path_for_fixture(fixture_path)
        if not schema_path.exists():
            findings.append(
                {
                    "fixture": str(fixture_path),
                    "schema": str(schema_path),
                    "expected": "valid",
                    "errors": ["schema not found"],
                }
            )
            continue
        errors = validate_fixture(schema_path, fixture_path)
        if errors:
            findings.append(
                {
                    "fixture": str(fixture_path),
                    "schema": str(schema_path),
                    "expected": "valid",
                    "errors": errors,
                }
            )
    for fixture_path in sorted(FIXTURES_DIR.glob("*.invalid.json")):
        schema_path = _schema_path_for_fixture(fixture_path)
        if not schema_path.exists():
            findings.append(
                {
                    "fixture": str(fixture_path),
                    "schema": str(schema_path),
                    "expected": "invalid",
                    "errors": ["schema not found"],
                }
            )
            continue
        errors = validate_fixture(schema_path, fixture_path)
        if not errors:
            findings.append(
                {
                    "fixture": str(fixture_path),
                    "schema": str(schema_path),
                    "expected": "invalid",
                    "errors": ["fixture unexpectedly valid"],
                }
            )
    return findings


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate JSON fixtures against schemas.")
    parser.parse_args(argv)
    findings = validate_fixtures()
    status = "ok" if not findings else "error"
    print(json.dumps({"status": status, "findings": findings}, indent=2, sort_keys=True))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
