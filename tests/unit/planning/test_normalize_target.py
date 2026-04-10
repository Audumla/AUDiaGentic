"""Unit tests for planning target normalization."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.hook_mgr import normalize_target


@pytest.mark.parametrize("raw,expected", [
    ("PKT-PRV-061",          "packet:PKT-PRV-061"),
    ("pkt-prv-061",          "packet:PKT-PRV-061"),
    ("PKT-INFRA-003",        "packet:PKT-INFRA-003"),
    ("packet:PKT-PRV-061",   "packet:PKT-PRV-061"),
    ("job:job_20240407_001", "job:job_20240407_001"),
    ("job_20240407_001",     "job:job_20240407_001"),
    ("adhoc",                "adhoc"),
    ("artifact:art_001",     "artifact:art_001"),
    (None,                   "adhoc"),
    ("",                     "adhoc"),
    ("  ",                   "adhoc"),
    ("free text",            "free text"),  # unrecognised — pass through
])
def test_normalize_target(raw, expected) -> None:
    assert normalize_target(raw) == expected
