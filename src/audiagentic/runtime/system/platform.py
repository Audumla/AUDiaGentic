"""Runtime system environment utilities.

Platform detection, process identity, and other runtime environment
information that foundation and components may consume.
"""
from __future__ import annotations

import sys


def platform_key() -> str:
    """Return a stable platform identifier: 'win', 'darwin', or 'linux'.

    Canonical source for platform detection across the codebase.
    """
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


__all__ = [
    "platform_key",
]
