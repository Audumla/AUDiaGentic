"""Architecture guard: every source package directory is importable (CC36).

Catches missing ``__init__.py`` gaps like ``components/providers/services/``
(present since commit 5edb620a, fixed by chg_20260714_031444) that make a
directory silently un-importable as a package.
"""

from __future__ import annotations

from pathlib import Path

import audiagentic

_EXCLUDED_DIR_NAMES = {"__pycache__"}


def test_every_package_directory_has_init() -> None:
    src_root = Path(audiagentic.__file__).parent
    missing: list[str] = []
    for directory in sorted(p for p in src_root.rglob("*") if p.is_dir()):
        if any(part in _EXCLUDED_DIR_NAMES for part in directory.parts):
            continue
        if not any(child.suffix == ".py" for child in directory.iterdir()):
            continue  # data-only directory (config/templates), not a package
        if not (directory / "__init__.py").exists():
            missing.append(str(directory.relative_to(src_root)))
    assert not missing, "package directories missing __init__.py:\n" + "\n".join(missing)
