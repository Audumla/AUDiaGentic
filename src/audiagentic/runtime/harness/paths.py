"""Generic package-root resolution and canonical config paths for harness modules.

All harnesses use find_package_root() and the _RIG_CONFIG / _HARNESS_CONFIG
constants from here. Nothing harness-specific should define its own path helpers.
"""
from __future__ import annotations

from pathlib import Path


def find_package_root(start: Path) -> Path:
    """Walk up from start until a directory named 'audiagentic' is found."""
    current = start.resolve()
    while current != current.parent:
        if current.name == "audiagentic":
            return current
        current = current.parent
    raise RuntimeError(f"Could not find 'audiagentic' package root from {start}")


_PKG_ROOT = find_package_root(Path(__file__))
_RIG_CONFIG = _PKG_ROOT / "config" / "provisioning" / "rig" / "rig.yaml"
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"
