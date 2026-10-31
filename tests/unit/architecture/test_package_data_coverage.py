"""Every runtime data file under src/audiagentic must ship in the wheel.

Files missing from [tool.setuptools.package-data] exist in a source checkout,
so tests pass there, but an installed package fails at runtime (for example
CFG-CONF-001 on a missing default, or gpt-auto losing its defaults).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")

REPO = Path(__file__).resolve().parents[3]
PACKAGE = REPO / "src" / "audiagentic"
# Documentation only; never read at runtime.
DOCS_ONLY = {"README.md", "INSTALL_MAP.md"}


def _pattern(glob: str) -> re.Pattern[str]:
    parts = []
    for token in re.split(r"(\*\*/|\*\*|\*)", glob):
        if token == "**/":
            parts.append("(?:.*/)?")
        elif token == "**":
            parts.append(".*")
        elif token == "*":
            parts.append("[^/]*")
        else:
            parts.append(re.escape(token))
    return re.compile("".join(parts) + r"\Z")


def test_runtime_data_files_are_package_data() -> None:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = [_pattern(glob) for glob in config["tool"]["setuptools"]["package-data"]["audiagentic"]]
    missing = sorted(
        relative
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and path.suffix not in {".py", ".pyc"}
        and "__pycache__" not in path.parts
        and path.name not in DOCS_ONLY
        and not any(pattern.match(relative := path.relative_to(PACKAGE).as_posix()) for pattern in patterns)
    )
    assert missing == [], f"add package-data patterns for: {missing}"
