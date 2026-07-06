from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.paths.names import find_package_root as _find_package_root


def find_package_root(start: Path) -> Path:
    """Walk up from start until a directory named 'audiagentic' is found.

    Delegates to the central resolver in foundation/paths/names.py.
    """
    return _find_package_root(start)
