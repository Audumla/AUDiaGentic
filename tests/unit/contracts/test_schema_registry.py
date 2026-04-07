from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.schema_registry import SCHEMA_DIR, iter_schema_paths


def test_canonical_schema_dir_exists() -> None:
    assert SCHEMA_DIR.is_dir()


def test_canonical_schema_dir_has_expected_content() -> None:
    assert iter_schema_paths()
