"""Canonical schema path resolution for AUDiaGentic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

AUDIAGENTIC_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = AUDIAGENTIC_ROOT / "foundation" / "contracts" / "schemas"


def schema_filename(stem: str) -> str:
    return f"{stem}.schema.json"


def schema_path(stem: str) -> Path:
    path = SCHEMA_DIR / schema_filename(stem)
    if not path.exists():
        raise FileNotFoundError(f"canonical schema not found: {path}")
    return path


def read_schema(stem: str) -> dict[str, Any]:
    return json.loads(schema_path(stem).read_text(encoding="utf-8"))


def validate_with_schema(stem: str, payload: Any) -> list[str]:
    """Return sorted validation error messages for a canonical schema."""
    validator = Draft202012Validator(read_schema(stem))
    return sorted(error.message for error in validator.iter_errors(payload))


def iter_schema_paths() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.json"))
