from __future__ import annotations

import shutil
import sys


def tool_available(name: str) -> bool:
    """Return True if the named executable is on PATH."""
    return shutil.which(name) is not None


def detect_pkg_manager() -> str | None:
    """Return the first supported package manager found on the current platform."""
    if sys.platform.startswith("win"):
        for pm in ("winget", "scoop", "choco"):
            if tool_available(pm):
                return pm
    elif sys.platform == "darwin":
        if tool_available("brew"):
            return "brew"
    else:
        for pm in ("apt", "dnf", "pacman"):
            if tool_available(pm):
                return pm
    return None


def platform_key() -> str:
    """Return a stable platform identifier for use in PlatformRecipe fallback keys."""
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"
