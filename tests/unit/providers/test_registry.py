from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.config.provider_registry import load_provider_registry


def _load_fixture(name: str) -> dict:
    return json.loads((ROOT / "docs" / "examples" / "fixtures" / name).read_text(encoding="utf-8"))


def test_registry_loads_valid_descriptor() -> None:
    descriptor = _load_fixture("provider-descriptor.valid.json")
    registry = load_provider_registry([descriptor])
    assert registry[descriptor["provider-id"]]["install-mode"] == descriptor["install-mode"]


def test_registry_rejects_invalid_descriptor() -> None:
    descriptor = _load_fixture("provider-descriptor.invalid.json")
    try:
        load_provider_registry([descriptor])
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected validation error")


def test_registry_rejects_duplicate_provider_id() -> None:
    descriptor = _load_fixture("provider-descriptor.valid.json")
    try:
        load_provider_registry([descriptor, descriptor])
    except AudiaGenticError as exc:
        assert exc.kind == "business-rule"
    else:
        raise AssertionError("expected duplicate provider error")
