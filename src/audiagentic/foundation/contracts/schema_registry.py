"""Canonical schema path resolution for AUDiaGentic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


AUDIAGENTIC_ROOT = Path(__file__).resolve().parents[2]  # src/audiagentic/
SCHEMA_DIR = AUDIAGENTIC_ROOT / "foundation" / "contracts" / "schemas"
PLANNING_SCHEMA_DIR = SCHEMA_DIR / "planning"


def schema_filename(stem: str) -> str:
    return f"{stem}.schema.json"


def schema_path(stem: str) -> Path:
    path = SCHEMA_DIR / schema_filename(stem)
    if not path.exists():
        raise FileNotFoundError(f"canonical schema not found: {path}")
    return path


def planning_schema_path(stem: str) -> Path:
    path = PLANNING_SCHEMA_DIR / schema_filename(stem)
    if not path.exists():
        raise FileNotFoundError(f"planning schema not found: {path}")
    return path


def read_schema(stem: str) -> dict[str, Any]:
    return json.loads(schema_path(stem).read_text(encoding="utf-8"))


def read_planning_schema(stem: str) -> dict[str, Any]:
    return json.loads(planning_schema_path(stem).read_text(encoding="utf-8"))


def iter_schema_paths() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.json"))


def iter_planning_schema_paths() -> list[Path]:
    return sorted(PLANNING_SCHEMA_DIR.glob("*.json"))
