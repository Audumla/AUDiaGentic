"""Shipped source carries no temporary debug instrumentation or machine-specific absolute paths."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "audiagentic"
TEMPORARY = re.compile(r"TEMPORARY\s+\w+\s+debug\s+instrumentation", re.IGNORECASE)
# A string literal that starts with a Windows drive path under a user profile or temp directory.
DRIVE_PATH = re.compile(r"""['"]C:\\\\?[^'"\n]*(?:Users|AppData|Temp)[^'"\n]*['"]""", re.IGNORECASE)


def _python_files() -> list[Path]:
    return [path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts]


def test_no_temporary_debug_instrumentation_is_shipped() -> None:
    found = [str(path.relative_to(SRC)) for path in _python_files() if TEMPORARY.search(path.read_text(encoding="utf-8"))]
    assert not found, f"temporary debug instrumentation left in: {found}"


def test_no_machine_specific_drive_paths_in_source_strings() -> None:
    found = [str(path.relative_to(SRC)) for path in _python_files() if DRIVE_PATH.search(path.read_text(encoding="utf-8"))]
    assert not found, f"machine-specific absolute paths in source: {found}"
