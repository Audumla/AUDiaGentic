from __future__ import annotations

from audiagentic.foundation.contracts.schema_registry import SCHEMA_DIR, iter_schema_paths


def test_canonical_schema_dir_exists() -> None:
    assert SCHEMA_DIR.is_dir()


def test_canonical_schema_dir_has_expected_content() -> None:
    assert iter_schema_paths()
