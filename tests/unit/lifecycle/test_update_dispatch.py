from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.lifecycle.update_dispatch import parse_version, select_update_module


def test_select_update_module_same_major() -> None:
    module = select_update_module("1.2.0", "1.3.0")
    assert module == "update_v1"


def test_select_update_module_different_major_raises() -> None:
    try:
        select_update_module("1.2.0", "2.0.0")
    except AudiaGenticError as exc:
        assert exc.kind == "business-rule"
    else:
        raise AssertionError("expected business-rule error")


def test_parse_version_invalid() -> None:
    try:
        parse_version("1.2")
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected validation error")
