"""Generic package-root resolution and canonical config paths for harness modules.

All harnesses use find_package_root() and the _HARNESS_CONFIG
constants from here. Nothing harness-specific should define its own path helpers.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.paths.package import find_package_root

_PKG_ROOT = find_package_root(Path(__file__))
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"
